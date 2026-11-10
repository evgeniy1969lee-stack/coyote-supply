"""Per-café observations from a live counter camera."""

import hashlib
import sqlite3
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, Field, UUID4

from .drafts import DraftStore
from .schemas import ContractModel, Id
from .shift import ShiftService
from .vision import FrameTooLarge, InvalidFrame, VisionUnavailable, read_frame
from .vision_labels import analyze_label

MARKER_PREFIX = "coyote:"
JOURNAL_LIMIT = 500


class CodeObservation(ContractModel):
    eventId: UUID4
    stationId: UUID4
    code: Annotated[str, Field(max_length=70)]


class LiveEvent(ContractModel):
    eventId: UUID
    stationId: UUID
    storeId: Id
    ingredientId: Id
    ingredientName: str
    source: Literal["code", "model", "label"]
    observedAt: AwareDatetime


class LiveProduct(ContractModel):
    ingredientId: Id
    name: str
    code: str


class LiveOverview(ContractModel):
    storeId: Id
    products: list[LiveProduct]
    events: list[LiveEvent]


class LiveFrame(ContractModel):
    ingredientId: Id | None = None
    ingredientName: str | None = None
    event: LiveEvent | None = None


def initialize_journal(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS vision_live_events (
            sequence INTEGER PRIMARY KEY,
            store_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            ingredient_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE (store_id, event_id)
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS vision_live_by_store
        ON vision_live_events (store_id, sequence)
    """)


def append_event(connection: sqlite3.Connection, event: LiveEvent) -> LiveEvent:
    existing = connection.execute(
        "SELECT payload FROM vision_live_events WHERE store_id = ? AND event_id = ?",
        (event.storeId, str(event.eventId)),
    ).fetchone()
    if existing:
        saved = LiveEvent.model_validate_json(existing[0])
        if (saved.stationId, saved.ingredientId, saved.source) != (event.stationId, event.ingredientId, event.source):
            raise HTTPException(409, "Этот ID уже связан с другим наблюдением.")
        return saved
    connection.execute(
        """INSERT INTO vision_live_events
           (store_id, event_id, station_id, ingredient_id, observed_at, payload) VALUES (?, ?, ?, ?, ?, ?)""",
        (event.storeId, str(event.eventId), str(event.stationId), event.ingredientId,
         event.observedAt.isoformat(), event.model_dump_json()),
    )
    connection.execute("""
        DELETE FROM vision_live_events WHERE store_id = ? AND sequence IN (
            SELECT sequence FROM vision_live_events WHERE store_id = ?
            ORDER BY sequence DESC LIMIT -1 OFFSET ?
        )
    """, (event.storeId, event.storeId, JOURNAL_LIMIT))
    return event


class LabelStreak:
    """One reading needs corroboration from a different frame."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._frames: OrderedDict[tuple[str, UUID], tuple[str, bytes, float]] = OrderedDict()

    def matches(self, key: tuple[str, UUID], ingredient: str | None, frame: bytes) -> bool:
        with self._lock:
            previous = self._frames.pop(key, None)
            if ingredient is None:
                return False
            stamp = monotonic()
            digest = hashlib.sha256(frame).digest()
            self._frames[key] = (ingredient, digest, stamp)
            if len(self._frames) > 256:
                self._frames.popitem(last=False)
            return bool(previous and previous[0] == ingredient and previous[1] != digest and stamp - previous[2] <= 75)


def live_router(database: DraftStore, get_shift: Callable[[], ShiftService]) -> APIRouter:
    router = APIRouter(prefix="/api/stores/{id}/vision/live", tags=["Vision Live"])
    streak = LabelStreak()

    def products(id: str) -> dict[str, str]:
        shift = get_shift()
        store = shift.stores.get(id)
        if store is None:
            raise HTTPException(404, "Точка не найдена.")
        if shift.dataset.data_mode != "synthetic":
            raise HTTPException(403, "Для рабочей точки нужен закрытый контур Vision.")
        return {key: shift.dataset.catalog[key].name for key in store.inventory}

    @router.get("", response_model=LiveOverview)
    def overview(id: str) -> LiveOverview:
        catalog = products(id)
        with database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM vision_live_events WHERE store_id = ? ORDER BY sequence DESC LIMIT 40", (id,),
            ).fetchall()
        return LiveOverview(
            storeId=id,
            products=[LiveProduct(ingredientId=key, name=name, code=MARKER_PREFIX + key) for key, name in catalog.items()],
            events=[LiveEvent.model_validate_json(row[0]) for row in rows],
        )

    @router.post("/events", response_model=LiveEvent)
    def code_seen(id: str, request: CodeObservation) -> LiveEvent:
        catalog = products(id)
        ingredient = request.code.removeprefix(MARKER_PREFIX)
        if request.code == ingredient or ingredient not in catalog:
            raise HTTPException(422, "Эта метка не привязана к продукту выбранной точки.")
        event = LiveEvent(
            eventId=request.eventId, stationId=request.stationId, storeId=id, ingredientId=ingredient,
            ingredientName=catalog[ingredient], source="code", observedAt=datetime.now(UTC),
        )
        with database.transaction(write=True) as connection:
            return append_event(connection, event)

    def record_label(id: str, station: UUID, ingredient: str, name: str) -> LiveEvent | None:
        now = datetime.now(UTC)
        with database.transaction(write=True) as connection:
            seen = connection.execute(
                """SELECT 1 FROM vision_live_events WHERE store_id = ? AND station_id = ?
                   AND ingredient_id = ? AND observed_at >= ? LIMIT 1""",
                (id, str(station), ingredient, (now - timedelta(seconds=60)).isoformat()),
            ).fetchone()
            if seen:
                return None
            return append_event(connection, LiveEvent(
                eventId=uuid4(), stationId=station, storeId=id, ingredientId=ingredient,
                ingredientName=name, source="label", observedAt=now,
            ))

    @router.post("/frames/{station}", response_model=LiveFrame)
    async def frame_seen(id: str, station: UUID4, request: Request) -> LiveFrame:
        catalog = products(id)
        try:
            frame = await read_frame(request)
            ingredient = await run_in_threadpool(analyze_label, frame)
        except FrameTooLarge:
            raise HTTPException(413, "Кадр слишком большой.") from None
        except InvalidFrame:
            raise HTTPException(422, "Не удалось прочитать кадр.") from None
        except VisionUnavailable:
            raise HTTPException(503, "Распознавание этикетки пока недоступно. Live повторит попытку.") from None
        ingredient = ingredient if ingredient in catalog else None
        confirmed = streak.matches((id, station), ingredient, frame)
        if ingredient is None:
            return LiveFrame()
        event = await run_in_threadpool(record_label, id, station, ingredient, catalog[ingredient]) if confirmed else None
        return LiveFrame(ingredientId=ingredient, ingredientName=catalog[ingredient], event=event)

    return router
