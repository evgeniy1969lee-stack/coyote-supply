import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .schemas import (
    MAX_SAFE_INTEGER, Draft, DraftRequest, DraftRow, ErrorDetail, Forecast,
)


class DraftStore:
    """One document per store keeps the saved price snapshot in a single atomic write."""

    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    store_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
            """)

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection

    @staticmethod
    def get(connection: sqlite3.Connection, store_id: str) -> Draft | None:
        row = connection.execute(
            "SELECT payload FROM drafts WHERE store_id = ?", (store_id,),
        ).fetchone()
        return Draft.model_validate_json(row[0]) if row is not None else None

    @staticmethod
    def replace(connection: sqlite3.Connection, store_id: str, draft: Draft | None) -> None:
        if draft is None:
            connection.execute("DELETE FROM drafts WHERE store_id = ?", (store_id,))
        else:
            connection.execute("""
                INSERT INTO drafts (store_id, payload) VALUES (?, ?)
                ON CONFLICT(store_id) DO UPDATE SET payload = excluded.payload
            """, (store_id, draft.model_dump_json()))


def price_draft(request: DraftRequest, forecast: Forecast) -> tuple[Draft | None, list[ErrorDetail]]:
    catalog = {item.ingredientId: item for item in forecast.ingredients}
    seen: set[str] = set()
    rows: list[DraftRow] = []
    errors: list[ErrorDetail] = []
    for index, row in enumerate(request.rows):
        path = f"rows.{index}"
        item = catalog.get(row.ingredientId)
        if row.ingredientId in seen:
            errors.append(ErrorDetail(path=f"{path}.ingredientId", reason="duplicate_ingredient"))
            continue
        seen.add(row.ingredientId)
        if item is None:
            errors.append(ErrorDetail(path=f"{path}.ingredientId", reason="unknown_ingredient"))
            continue
        if item.recommendedQty is None:
            errors.append(ErrorDetail(path=f"{path}.ingredientId", reason="recommendation_unavailable"))
            continue
        count, remainder = divmod(row.quantity, item.packQty)
        if remainder:
            errors.append(ErrorDetail(path=f"{path}.quantity", reason="not_multiple_of_pack"))
            continue
        total = count * item.packPriceKzt
        if total > MAX_SAFE_INTEGER:
            errors.append(ErrorDetail(path=f"{path}.quantity", reason="amount_out_of_range"))
            continue
        rows.append(DraftRow(
            ingredientId=row.ingredientId, quantity=row.quantity, packCount=count,
            packPriceKzt=item.packPriceKzt, lineTotalKzt=total,
        ))

    total = sum(row.lineTotalKzt for row in rows)
    if total > MAX_SAFE_INTEGER:
        errors.append(ErrorDetail(path="rows", reason="amount_out_of_range"))
    if errors or not rows:
        return None, errors
    return Draft(forecastId=request.forecastId, rows=rows, totalKzt=total, savedAt=datetime.now(UTC)), []
