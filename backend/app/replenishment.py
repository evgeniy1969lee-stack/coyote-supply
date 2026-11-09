import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .data import Dataset, Delivery, Ingredient, StoreData
from .forecast import MODEL_VERSION, ConsumptionHistory, aggregate_consumption, forecast_demand
from .inventory import simulate
from .schemas import (
    Excess, Explanation, Forecast, IngredientForecast, InsufficientData, Risk, Schedule,
    Stockout,
)

POLICY_VERSION = "fefo-order-v1"


def next_schedule(store: StoreData) -> Schedule | None:
    zone = ZoneInfo(store.info.timeZone)
    as_of = store.info.asOf.astimezone(zone)
    available = []
    for rule in store.calendar:
        earliest = as_of.date() + timedelta(
            days=rule.lead_days + (as_of.time() > rule.deadline_time),
        )
        arrival = earliest + timedelta(days=(rule.weekday - earliest.weekday()) % 7)
        deadline = datetime.combine(arrival - timedelta(days=rule.lead_days), rule.deadline_time, zone)
        available.append((arrival, deadline))
        available.append((arrival + timedelta(days=7), deadline + timedelta(days=7)))
    if not available:
        return None
    available.sort(key=lambda slot: slot[0])
    (arrival, deadline), (next_arrival, _) = available[:2]
    return Schedule(orderDeadlineAt=deadline, arrivalDate=arrival, nextArrivalDate=next_arrival)


def recommend_ingredient(
    store: StoreData, ingredient_id: str, item: Ingredient,
    history: ConsumptionHistory, deliveries: list[Delivery], schedule: Schedule | None,
) -> IngredientForecast:
    stock = store.inventory[ingredient_id]
    common = dict(
        ingredientId=ingredient_id, name=item.name, unit=item.unit, onHandQty=stock.on_hand,
        packQty=item.pack_qty, packPriceKzt=item.pack_price_kzt,
    )
    risks: list[Risk] = []
    demand = {}
    if stock.on_hand is None:
        risks.append(InsufficientData(reason="missing_on_hand"))
    elif store.info.asOf - stock.observed_at > timedelta(hours=store.max_inventory_age_hours):
        risks.append(InsufficientData(reason="stale_on_hand"))
    if schedule is None:
        risks.append(InsufficientData(reason="missing_schedule"))
    else:
        cutoff = store.as_of_date
        dates = [cutoff + timedelta(days=i) for i in range((schedule.nextArrivalDate - cutoff).days)]
        estimates = forecast_demand(history, cutoff, dates)
        demand = {estimate.date: estimate.quantity for estimate in estimates
                  if estimate.quantity is not None}
        if any(estimate.missing_recipe for estimate in estimates):
            risks.append(InsufficientData(reason="missing_recipe"))
        if len(demand) != len(dates):
            risks.append(InsufficientData(reason="insufficient_history"))
    if risks:
        return IngredientForecast(
            **common, daily=[], risks=risks, recommendedQty=None, explanation=None,
            dataStatus="needs_review",
        )

    assert schedule is not None
    daily, expiry = simulate(stock, demand, deliveries, item.track_expiry)
    before = [row for row in daily if row.date < schedule.arrivalDate]
    shortages = [row for row in before if row.unmetQty]
    shortage_qty = sum(row.unmetQty for row in shortages)
    if shortages:
        risks.append(Stockout(
            date=shortages[0].date, firstUnmetQty=shortages[0].unmetQty, quantity=shortage_qty,
        ))
    risks.extend(expiry)
    if item.track_expiry and any(row.expiringQty is None for row in daily):
        risks.append(InsufficientData(reason="unknown_lot_expiry"))
    ending = daily[-1]
    if ending.closingQty > stock.max_stock:
        risks.append(Excess(date=ending.date, quantity=ending.closingQty - stock.max_stock))

    uncovered = sum(row.unmetQty for row in daily if row.date >= schedule.arrivalDate)
    unrounded = uncovered + max(0, stock.safety_stock - ending.closingQty)
    rounded = ((unrounded + item.pack_qty - 1) // item.pack_qty) * item.pack_qty
    return IngredientForecast(
        **common, daily=daily, risks=risks, recommendedQty=rounded, dataStatus="ok",
        explanation=Explanation(
            demandBeforeArrivalQty=sum(row.demandQty for row in before),
            shortageBeforeArrivalQty=shortage_qty, uncoveredWindowDemandQty=uncovered,
            safetyStockQty=stock.safety_stock, endStockWithoutOrderQty=ending.closingQty,
            unroundedOrderQty=unrounded,
        ),
    )


def build_forecast(dataset: Dataset, store: StoreData) -> Forecast:
    # Hash the snapshot as well as the policy versions. Changes in another store's
    # sales or stock do not invalidate this store's saved draft.
    source = {
        "dataset": dataset.version, "model": MODEL_VERSION, "policy": POLICY_VERSION,
        "catalog": {key: dataset.catalog[key].model_dump(mode="json") for key in store.inventory},
        "recipes": [recipe.model_dump(mode="json") for recipe in dataset.recipes],
        "store": store.model_dump(mode="json"),
    }
    digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    schedule = next_schedule(store)
    history = aggregate_consumption(store, dataset.recipes)
    deliveries: dict[str, list[Delivery]] = defaultdict(list)
    for delivery in store.deliveries:
        deliveries[delivery.ingredient_id].append(delivery)
    return Forecast(
        storeId=store.info.storeId, forecastId=f"{store.info.storeId}-{store.as_of_date}-{digest}",
        asOf=store.info.asOf, schedule=schedule,
        ingredients=[
            recommend_ingredient(store, key, dataset.catalog[key], history[key], deliveries[key], schedule)
            for key in store.inventory
        ],
    )
