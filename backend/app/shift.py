"""Operational shift state over the supply forecast and a persisted stock journal."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from .data import Dataset, Recipe, StoreData
from .replenishment import build_forecast
from .schemas import (
    ContractModel, Draft, Expiry, Forecast, Id, IngredientForecast, PositiveQty, Qty,
    Stockout, Unit,
)

EventId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
VISION_INGREDIENTS = frozenset({"milk", "oat-milk", "cream"})


class LossRequest(ContractModel):
    eventId: EventId
    forecastId: Id
    ingredientId: Id
    quantity: PositiveQty


class ConsumptionRequest(LossRequest):
    recipeSku: Id


class LossEffect(ContractModel):
    onHandQty: Qty
    shortageQty: Qty | None
    recommendedQty: Qty | None


class StockEvent(ContractModel):
    eventId: EventId
    ingredientId: Id
    name: str
    unit: Unit
    quantity: PositiveQty
    recordedAt: AwareDatetime
    before: LossEffect
    after: LossEffect
    kind: Literal["loss", "consumption"] = "loss"
    recipeSku: Id | None = None
    todayDemandBefore: Qty | None = None
    todayDemandAfter: Qty | None = None


class Guardian(ContractModel):
    state: Literal["alert", "watch", "calm"]
    title: str
    message: str


class ShiftAction(ContractModel):
    id: Literal["stockout", "order", "expiry", "data"]
    priority: Literal["urgent", "planned", "done"]
    title: str
    detail: str


class ShiftOverview(ContractModel):
    storeId: Id
    shiftDate: date
    forecast: Forecast
    draft: Draft | None
    guardian: Guardian
    actions: Annotated[list[ShiftAction], Field(max_length=4)]
    recentLosses: list[StockEvent]
    recentConsumptions: list[StockEvent]


class LossRejected(ValueError):
    def __init__(self, path: str, reason: str):
        super().__init__(reason)
        self.path = path
        self.reason = reason


class ShiftChanged(ValueError):
    pass


@dataclass(frozen=True)
class ShiftSnapshot:
    store: StoreData
    forecast: Forecast
    events: list[StockEvent]
    consumed_today: dict[str, int]


def vision_recipes(dataset: Dataset, day: date) -> list[Recipe]:
    return [
        recipe for recipe in dataset.recipes
        if recipe.valid_from <= day and (recipe.valid_until is None or day < recipe.valid_until)
        and VISION_INGREDIENTS.intersection(recipe.usage)
    ]


def describe_quantity(quantity: int, unit: Unit) -> str:
    if unit == "pcs":
        return f"{quantity} шт."
    if quantity < 1_000:
        return f"{quantity} {('мл' if unit == 'ml' else 'г')}"
    whole, fraction = divmod(quantity, 1_000)
    number = f"{whole},{fraction:03}".rstrip("0") if fraction else str(whole)
    return f"{number} {('л' if unit == 'ml' else 'кг')}"


def deduct_stock(store: StoreData, ingredient_id: str, quantity: int) -> StoreData:
    stock = store.inventory.get(ingredient_id)
    if stock is None:
        raise LossRejected("ingredientId", "unknown_ingredient")
    if stock.on_hand is None:
        raise LossRejected("ingredientId", "unknown_on_hand")
    if store.info.asOf - stock.observed_at > timedelta(hours=store.max_inventory_age_hours):
        raise LossRejected("ingredientId", "stale_on_hand")
    if quantity > stock.on_hand:
        raise LossRejected("quantity", "insufficient_stock")

    lots = stock.lots
    if lots is not None:
        remaining = quantity
        updated = []
        for lot in sorted(lots, key=lambda item: (item.expires_on or date.max, item.id)):
            if lot.expires_on is not None and lot.expires_on < store.as_of_date:
                updated.append(lot)
                continue
            removed = min(remaining, lot.quantity)
            remaining -= removed
            if lot.quantity > removed:
                updated.append(lot.model_copy(update={"quantity": lot.quantity - removed}))
        if remaining:
            raise LossRejected("quantity", "insufficient_stock")
        lots = updated
    adjusted = stock.model_copy(update={"on_hand": stock.on_hand - quantity, "lots": lots})
    return store.model_copy(update={"inventory": {**store.inventory, ingredient_id: adjusted}})


def _effect(item: IngredientForecast) -> LossEffect:
    assert item.onHandQty is not None
    return LossEffect(
        onHandQty=item.onHandQty,
        shortageQty=item.explanation.shortageBeforeArrivalQty if item.explanation else None,
        recommendedQty=item.recommendedQty,
    )


class ShiftService:
    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.stores = {store.info.storeId: store for store in dataset.stores}
        self.baselines = {
            key: build_forecast(dataset, store) for key, store in self.stores.items()
        }

    @staticmethod
    def initialize(connection: sqlite3.Connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS shift_losses (
                sequence INTEGER PRIMARY KEY,
                baseline_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE (baseline_id, event_id)
            )
        """)

    def current(self, connection: sqlite3.Connection, store_id: str) -> ShiftSnapshot:
        store = self.stores[store_id]
        baseline = self.baselines[store_id]
        rows = connection.execute(
            "SELECT payload FROM shift_losses WHERE baseline_id = ? ORDER BY sequence",
            (baseline.forecastId,),
        )
        events = [StockEvent.model_validate_json(payload) for (payload,) in rows]
        consumed_today: dict[str, int] = {}
        for event in events:
            store = deduct_stock(store, event.ingredientId, event.quantity)
            if event.kind == "consumption":
                consumed_today[event.ingredientId] = consumed_today.get(event.ingredientId, 0) + event.quantity
        forecast = build_forecast(self.dataset, store, consumed_today=consumed_today) if events else baseline
        return ShiftSnapshot(store, forecast, events, consumed_today)

    def record(self, connection: sqlite3.Connection, store_id: str, request: LossRequest) -> ShiftSnapshot:
        snapshot = self.current(connection, store_id)
        recipe_sku = request.recipeSku if isinstance(request, ConsumptionRequest) else None
        duplicate = next((event for event in snapshot.events if event.eventId == request.eventId), None)
        if duplicate is not None:
            if (duplicate.ingredientId, duplicate.quantity, duplicate.recipeSku) != (
                request.ingredientId, request.quantity, recipe_sku,
            ):
                raise LossRejected("eventId", "event_id_reused")
            return snapshot
        if request.forecastId != snapshot.forecast.forecastId:
            raise ShiftChanged

        consumed_today = snapshot.consumed_today
        if recipe_sku is not None:
            recipe = next((row for row in vision_recipes(self.dataset, snapshot.store.as_of_date) if row.sku == recipe_sku), None)
            if recipe is None or request.ingredientId not in VISION_INGREDIENTS.intersection(recipe.usage):
                raise LossRejected("recipeSku", "ingredient_not_in_recipe")
            if self.dataset.catalog[request.ingredientId].unit != "ml":
                raise LossRejected("ingredientId", "unsupported_vision_unit")
            consumed_today = {
                **consumed_today,
                request.ingredientId: consumed_today.get(request.ingredientId, 0) + request.quantity,
            }

        store = deduct_stock(snapshot.store, request.ingredientId, request.quantity)
        forecast = build_forecast(self.dataset, store, consumed_today=consumed_today)
        before = next(item for item in snapshot.forecast.ingredients if item.ingredientId == request.ingredientId)
        after = next(item for item in forecast.ingredients if item.ingredientId == request.ingredientId)
        event = StockEvent(
            eventId=request.eventId, ingredientId=request.ingredientId, name=after.name, unit=after.unit,
            quantity=request.quantity, recordedAt=datetime.now(UTC), before=_effect(before), after=_effect(after),
            kind="consumption" if recipe_sku is not None else "loss", recipeSku=recipe_sku,
            todayDemandBefore=before.daily[0].demandQty if recipe_sku is not None and before.daily else None,
            todayDemandAfter=after.daily[0].demandQty if recipe_sku is not None and after.daily else None,
        )
        connection.execute(
            "INSERT INTO shift_losses (baseline_id, event_id, payload) VALUES (?, ?, ?)",
            (self.baselines[store_id].forecastId, request.eventId, event.model_dump_json()),
        )
        return ShiftSnapshot(store, forecast, [*snapshot.events, event], consumed_today)


def summarize_shift(snapshot: ShiftSnapshot, draft: Draft | None) -> ShiftOverview:
    forecast = snapshot.forecast
    items = forecast.ingredients
    stockout = min(
        ((item, risk) for item in items for risk in item.risks if isinstance(risk, Stockout)),
        key=lambda pair: (pair[1].date, pair[0].ingredientId), default=None,
    )
    expiry = min(
        ((item, risk) for item in items for risk in item.risks if isinstance(risk, Expiry)),
        key=lambda pair: (pair[1].date, pair[0].ingredientId), default=None,
    )
    actions: list[ShiftAction] = []
    ready = draft is not None and draft.forecastId == forecast.forecastId
    needs_review = [item.name for item in items if item.dataStatus == "needs_review"]

    if stockout:
        item, risk = stockout
        warning = f"{item.name} · риск нехватки с {risk.date:%d.%m}."
        detail = f"До поставки может не хватить {describe_quantity(risk.quantity, item.unit)}."
        actions.append(ShiftAction(id="stockout", priority="urgent", title="Подготовьтесь к нехватке", detail=f"{warning} {detail}"))
        available = describe_quantity(item.onHandQty, item.unit) if item.onHandQty is not None else "неизвестно"
        message = f"{warning} На складе {available}. {detail}"
        guardian = Guardian(
            state="alert",
            title="Риск нехватки до поставки",
            message=message,
        )
    elif needs_review:
        guardian = Guardian(
            state="watch", title="Сверим остатки",
            message="По части позиций не хватает данных. Уточните их перед заказом.",
        )
    else:
        guardian = Guardian(
            state="calm", title="Смена по плану",
            message="На текущем прогнозе дефицита до поставки нет.",
        )

    if draft is not None or any(item.recommendedQty for item in items):
        order_detail = (
            f"Сумма по серверу · {draft.totalKzt:,} ₸.".replace(",", " ") if ready and draft is not None
            else "После пересчёта проверьте сохранённые позиции." if draft is not None
            else "Проверьте объём, упаковки и дату поставки перед сохранением."
        )
        actions.append(ShiftAction(
            id="order", priority="done" if ready else "planned",
            title="Черновик сохранён" if ready else "Проверьте закупку", detail=order_detail,
        ))
    if expiry:
        item, risk = expiry
        actions.append(ShiftAction(
            id="expiry", priority="planned", title="Проверьте срок партии",
            detail=f"{item.name} · {describe_quantity(risk.quantity, item.unit)} под риском списания {risk.date:%d.%m}.",
        ))
    if needs_review:
        actions.append(ShiftAction(
            id="data", priority="planned", title="Сверьте данные склада", detail=", ".join(needs_review) + ".",
        ))
    return ShiftOverview(
        storeId=forecast.storeId, shiftDate=snapshot.store.as_of_date, forecast=forecast, draft=draft,
        guardian=guardian, actions=actions,
        recentLosses=[event for event in reversed(snapshot.events) if event.kind == "loss"][:5],
        recentConsumptions=[event for event in reversed(snapshot.events) if event.kind == "consumption"][:5],
    )
