from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.data import Dataset, Recipe, Sale
from backend.app.demo_data import load_demo
from backend.app.forecast import ConsumptionHistory, aggregate_consumption, forecast_demand
from backend.app.replenishment import build_forecast

CUTOFF = date(2026, 11, 9)


def test_weekday_median_rounds_up_and_uses_only_four_prior_observations():
    history = {
        CUTOFF - timedelta(weeks=week): qty
        for week, qty in enumerate([9000, 0, 3, 4, 1000, 9000])
    }
    history[CUTOFF - timedelta(days=1)] = 9000
    history[CUTOFF + timedelta(weeks=1)] = 9000
    result, = forecast_demand(ConsumptionHistory(history, set()), CUTOFF, [CUTOFF])
    assert result.quantity == 4
    assert [qty for _, qty in result.samples] == [0, 3, 4, 1000]


def test_missing_week_skipped_but_zero_counts_toward_minimum():
    recent = CUTOFF - timedelta(weeks=1)
    older = CUTOFF - timedelta(weeks=3)
    oldest = CUTOFF - timedelta(weeks=4)
    history = ConsumptionHistory({recent: 0, older: 20}, set())
    result, = forecast_demand(history, CUTOFF, [CUTOFF])
    assert result.quantity is None
    assert len(result.samples) == 2
    history.quantities[oldest] = 5
    result, = forecast_demand(history, CUTOFF, [CUTOFF])
    assert result.quantity == 5


def test_recipe_versions_local_date_and_sales_statuses():
    demo = load_demo()
    before, after = date(2026, 10, 11), date(2026, 10, 12)
    closed, missing, constrained = date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)
    first = Sale(id="sale-1", sku="latte-300", quantity=2, at="2026-10-11T18:59:00Z")
    second = Sale(id="sale-2", sku="latte-300", quantity=3, at="2026-10-11T19:00:00Z")
    cancelled = second.model_copy(update={"id": "sale-3", "status": "cancelled"})
    refunded = second.model_copy(update={"id": "sale-4", "status": "refunded"})
    excluded = second.model_copy(update={"id": "sale-5", "at": datetime.fromisoformat("2026-10-15T09:00:00+05:00")})
    store = demo.stores[0].model_copy(update={
        "observations": {before: "complete", after: "complete", closed: "complete",
                         missing: "missing", constrained: "stockout"},
        "sales": [first, first, second, cancelled, refunded, excluded],
    })
    history = aggregate_consumption(store, demo.recipes)
    assert history["milk"].quantities == {before: 480, after: 750, closed: 0}
    assert history["beans"].quantities == {before: 36, after: 54, closed: 0}


def test_missing_recipe_marks_affected_ingredients_and_skips_observation():
    demo = load_demo()
    store = demo.stores[0]
    recipes = [recipe for recipe in demo.recipes
               if recipe.sku != "latte-300" or recipe.valid_until is not None]
    history = aggregate_consumption(store, recipes)
    last_monday = CUTOFF - timedelta(weeks=1)
    assert last_monday in history["milk"].missing_recipe
    assert last_monday not in history["milk"].quantities
    assert last_monday in history["cream"].quantities
    forecast = build_forecast(demo.model_copy(update={"recipes": recipes}), store)
    milk, cream, *_ = forecast.ingredients
    assert milk.recommendedQty is None
    assert {risk.reason for risk in milk.risks} == {"missing_recipe"}
    assert cream.dataStatus == "ok"


def test_input_rejects_overlapping_recipes():
    demo = load_demo()
    conflicting = Recipe(sku="latte-300", valid_from="2026-10-11", usage={"milk": 260})
    with pytest.raises(ValidationError, match="Overlapping recipe"):
        Dataset(
            version=demo.version, catalog=demo.catalog, stores=demo.stores,
            recipes=[*demo.recipes, conflicting],
        )


def test_demo_input_is_deterministic_and_store_changes_are_isolated():
    first = load_demo()
    second = load_demo()
    assert first == second
    shymkent, almaty = second.stores
    assert len(shymkent.observations) == len(almaty.observations) == 70
    for store in second.stores:
        assert set(store.observations.values()) == {"complete", "missing", "stockout"}
        assert any(sale.status == "cancelled" for sale in store.sales)
    original = build_forecast(first, first.stores[0])
    almaty.sales.pop()
    assert build_forecast(second, shymkent).forecastId == original.forecastId
    shymkent.sales.pop()
    assert build_forecast(second, shymkent).forecastId != original.forecastId


def test_insufficient_history_cannot_be_treated_as_zero_demand():
    demo = load_demo()
    store = demo.stores[0]
    store.observations = {day: status for day, status in store.observations.items()
                          if day >= CUTOFF - timedelta(weeks=2)}
    milk = build_forecast(demo, store).ingredients[0]
    assert milk.recommendedQty is None
    assert milk.daily == []
    assert milk.risks[0].reason == "insufficient_history"
