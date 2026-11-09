from datetime import date, datetime, time, timedelta
from pathlib import Path
from random import Random
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from .data import Dataset, Observation, Sale, StoreData
from .schemas import Id, Qty

DEMO_PATH = Path(__file__).resolve().parents[1] / "data" / "demo-v1.json"


class DemoStore(StoreData):
    weekday_sales: dict[Id, Annotated[list[Qty], Field(min_length=7, max_length=7)]]
    missing_days: set[date]
    closed_days: set[date]
    stockout_days: set[date]
    observations: dict[date, Observation] = Field(default_factory=dict)
    sales: list[Sale] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_day_overrides(self):
        if (self.missing_days & self.closed_days or self.missing_days & self.stockout_days
                or self.closed_days & self.stockout_days):
            raise ValueError("Conflicting history day overrides")
        return self


class DemoConfig(Dataset):
    seed: int
    weeks: Annotated[int, Field(strict=True, ge=8, le=12)]
    stores: list[DemoStore]


def generate_history(store: DemoStore, weeks: int, seed: int) -> StoreData:
    rng = Random(f"{seed}:{store.info.storeId}")
    zone = ZoneInfo(store.info.timeZone)
    cutoff = store.as_of_date
    observations: dict[date, Observation] = {}
    sales = []

    # Four-week cycles vary the number of items sold while keeping the median stable.
    for days_ago in range(weeks * 7, 0, -1):
        day = cutoff - timedelta(days=days_ago)
        observations[day] = "complete"
        if day in store.missing_days:
            observations[day] = "missing"
            continue
        if day in store.closed_days:
            continue
        if day in store.stockout_days:
            observations[day] = "stockout"

        week = (days_ago - 1) // 7
        offset = (-1, 0, 0, 1)[week % 4]
        for sku, counts in store.weekday_sales.items():
            baseline = counts[day.weekday()]
            if baseline == 0:
                continue
            variation = offset if week < 4 else rng.randint(-3, 3)
            sold = max(1, baseline + variation)
            # Represent POS lines by time and SKU, with morning and afternoon sales.
            morning = rng.randint(sold // 3, max(sold // 3, sold * 2 // 3))
            for hour, quantity in [(10, morning), (15, sold - morning)]:
                if quantity:
                    sales.append(Sale(
                        id=f"{day}-{sku}-{hour}", sku=sku, quantity=quantity,
                        at=datetime.combine(day, time(hour, rng.randrange(60)), zone),
                    ))
        if day.day % 5 == 0:
            sales.append(Sale(
                id=f"{day}-cancelled", sku="latte-300", quantity=2, status="cancelled",
                at=datetime.combine(day, time(17), zone),
            ))

    fields = store.model_dump(include=set(StoreData.model_fields))
    return StoreData.model_validate(fields | {"observations": observations, "sales": sales})


def load_demo(path: Path = DEMO_PATH) -> Dataset:
    config = DemoConfig.model_validate_json(path.read_bytes())
    return Dataset(
        version=config.version, catalog=config.catalog, recipes=config.recipes,
        stores=[generate_history(store, config.weeks, config.seed) for store in config.stores],
    )
