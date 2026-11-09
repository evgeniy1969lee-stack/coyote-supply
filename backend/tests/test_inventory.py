from datetime import date, timedelta

from backend.app.data import Delivery, Inventory, Lot
from backend.app.demo_data import load_demo
from backend.app.inventory import simulate
from backend.app.replenishment import build_forecast, next_schedule

MON = date(2026, 11, 9)
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)


def test_fefo_and_inclusive_expiry_with_preexpired_stock():
    stock = Inventory(
        on_hand=30, observed_at="2026-11-09T07:00:00+05:00", max_stock=30,
        lots=[
            Lot(id="later", quantity=10, expires_on=WED),
            Lot(id="early", quantity=12, expires_on=TUE),
            Lot(id="expired", quantity=8, expires_on=MON - timedelta(days=1)),
        ],
    )
    days, risks = simulate(stock, {MON: 2, TUE: 1, WED: 11}, [], track_expiry=True)
    assert [day.closingQty for day in days] == [20, 10, 0]
    assert [day.expiringQty for day in days] == [0, 9, 0]
    assert [day.unmetQty for day in days] == [0, 0, 1]
    assert [(risk.lotId, risk.quantity, risk.date) for risk in risks] == [("early", 9, TUE)]


def test_confirmed_delivery_available_at_start_and_no_backfill():
    stock = Inventory(on_hand=0, observed_at="2026-11-09T07:00:00+05:00", max_stock=30)
    deliveries = [
        Delivery(ingredient_id="milk", arrives_on=TUE, lot=Lot(id="delivery", quantity=8, expires_on=TUE)),
        Delivery(ingredient_id="milk", arrives_on=MON, lot=Lot(id="pending", quantity=90), confirmed=False),
    ]
    days, risks = simulate(stock, {MON: 5, TUE: 7, WED: 2}, deliveries, track_expiry=True)
    assert [day.incomingQty for day in days] == [0, 8, 0]
    assert [day.unmetQty for day in days] == [5, 0, 2]
    assert risks[0].quantity == 1


def test_missing_lots_allow_recommendation_and_mark_unknown_expiry():
    demo = load_demo()
    cocoa = next(item for item in build_forecast(demo, demo.stores[0]).ingredients
                 if item.ingredientId == "cocoa")
    assert cocoa.dataStatus == "ok"
    assert cocoa.daily[0].expiringQty is None
    assert any(risk.type == "insufficient_data" and risk.reason == "unknown_lot_expiry"
               for risk in cocoa.risks)


def test_late_and_outside_window_deliveries_do_not_cover_earlier_shortages():
    demo = load_demo()
    store = demo.stores[0]
    baseline = build_forecast(demo, store).ingredients[0]
    assert baseline.explanation.uncoveredWindowDemandQty == 19000  # Sunday arrival excluded.
    store.deliveries.append(Delivery(
        ingredient_id="milk", arrives_on="2026-11-14",
        lot=Lot(id="saturday", quantity=9000, expires_on="2026-11-21"),
    ))
    milk = build_forecast(demo, store).ingredients[0]
    assert milk.explanation.shortageBeforeArrivalQty == 17000
    assert milk.explanation.uncoveredWindowDemandQty == 12000  # Thursday and Friday still count.
    assert milk.explanation.endStockWithoutOrderQty == 2000
    assert milk.explanation.unroundedOrderQty == 15000
    assert milk.recommendedQty == 18000


def test_deadline_is_inclusive_and_missed_slot_moves_to_sunday():
    demo = load_demo()
    store = demo.stores[0]
    schedule = next_schedule(store)
    assert schedule.arrivalDate == date(2026, 11, 12)
    store.info.asOf = schedule.orderDeadlineAt
    assert next_schedule(store).arrivalDate == schedule.arrivalDate
    store.info.asOf += timedelta(seconds=1)
    new_schedule = next_schedule(store)
    assert new_schedule.arrivalDate == date(2026, 11, 15)
    assert new_schedule.nextArrivalDate == date(2026, 11, 19)


def test_missing_schedule_and_stale_stock_require_review():
    demo = load_demo()
    almaty = demo.stores[1]
    cocoa = build_forecast(demo, almaty).ingredients[-1]
    assert cocoa.recommendedQty is None
    assert cocoa.risks[0].reason == "stale_on_hand"
    almaty.calendar = []
    forecast = build_forecast(demo, almaty)
    assert forecast.schedule is None
    assert forecast.ingredients[0].risks[0].reason == "missing_schedule"
