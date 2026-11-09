from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from .data import Recipe, StoreData

MODEL_VERSION = "weekday-median-v1"


@dataclass(frozen=True)
class ConsumptionHistory:
    # Absent dates are unusable. Present dates can have a confirmed zero.
    quantities: dict[date, int]
    missing_recipe: set[date]


@dataclass(frozen=True)
class DemandEstimate:
    date: date
    quantity: int | None
    samples: tuple[tuple[date, int], ...]
    missing_recipe: bool


def aggregate_consumption(
    store: StoreData, recipes: list[Recipe],
) -> dict[str, ConsumptionHistory]:
    zone = ZoneInfo(store.info.timeZone)
    cutoff = store.as_of_date
    by_sku: dict[str, list[Recipe]] = defaultdict(list)
    ingredients_by_sku: dict[str, set[str]] = defaultdict(set)
    for recipe in recipes:
        by_sku[recipe.sku].append(recipe)
        ingredients_by_sku[recipe.sku].update(recipe.usage)

    days = {day for day, status in store.observations.items()
            if day < cutoff and status == "complete"}
    history = {
        ingredient_id: ConsumptionHistory(dict.fromkeys(days, 0), set())
        for ingredient_id in store.inventory
    }
    seen = set()
    for sale in store.sales:
        day = sale.at.astimezone(zone).date()
        if day not in days or sale.status != "completed" or sale.id in seen:
            continue
        seen.add(sale.id)
        recipe = next((
            version for version in by_sku.get(sale.sku, ())
            if version.valid_from <= day
            and (version.valid_until is None or day < version.valid_until)
        ), None)
        if recipe is None:
            affected = ingredients_by_sku.get(sale.sku, store.inventory.keys())
            for ingredient_id in history.keys() & affected:
                history[ingredient_id].missing_recipe.add(day)
            continue
        for ingredient_id in history.keys() & recipe.usage.keys():
            history[ingredient_id].quantities[day] += sale.quantity * recipe.usage[ingredient_id]

    for series in history.values():
        for day in series.missing_recipe:
            del series.quantities[day]
    return history


def forecast_demand(
    history: ConsumptionHistory, as_of: date, dates: list[date],
) -> list[DemandEstimate]:
    weekdays: dict[int, list[date]] = defaultdict(list)
    for day in sorted(history.quantities.keys() | history.missing_recipe, reverse=True):
        if day < as_of:
            weekdays[day.weekday()].append(day)

    estimates = []
    for day in dates:
        candidates = weekdays[day.weekday()]
        valid = (past for past in candidates if past in history.quantities)
        samples = tuple((past, history.quantities[past]) for past in list(valid)[:4])
        missing_recipe = any(past in history.missing_recipe for past in candidates[:4])
        values = sorted(quantity for _, quantity in samples)
        quantity = None
        if len(values) == 3:
            quantity = values[1]
        elif len(values) == 4:
            quantity = (values[1] + values[2] + 1) // 2
        estimates.append(DemandEstimate(day, quantity, samples, missing_recipe))
    return estimates
