from collections import defaultdict
from datetime import date

from .data import Delivery, Inventory, Lot
from .schemas import Daily, Expiry


def simulate(
    stock: Inventory, demand: dict[date, int], deliveries: list[Delivery], track_expiry: bool,
) -> tuple[list[Daily], list[Expiry]]:
    if stock.on_hand is None:
        raise ValueError("Simulation requires known opening stock")

    lots = stock.lots
    if lots is None:
        lots = [Lot(id="opening-stock", quantity=stock.on_hand)] if stock.on_hand else []
    ordered_days = sorted(demand)
    if not ordered_days:
        return [], []
    # Opening snapshots can include stock that has already expired.
    active = [(lot, lot.quantity) for lot in lots
              if lot.expires_on is None or lot.expires_on >= ordered_days[0]]
    incoming: dict[date, list[Lot]] = defaultdict(list)
    for delivery in deliveries:
        if delivery.confirmed:
            incoming[delivery.arrives_on].append(delivery.lot)

    daily = []
    expiry = []
    for day in ordered_days:
        active.extend((lot, lot.quantity) for lot in incoming[day])
        active.sort(key=lambda item: (item[0].expires_on or date.max,
                                     item[0].expires_on is None, item[0].id))
        expiry_known = track_expiry and all(lot.expires_on is not None for lot, _ in active)
        unmet = demand[day]
        surviving = []
        expiring = 0
        for lot, available in active:
            used = min(available, unmet)
            unmet -= used
            remaining = available - used
            if remaining == 0:
                continue
            if lot.expires_on == day:
                expiry.append(Expiry(date=day, quantity=remaining, lotId=lot.id))
                expiring += remaining
            else:
                surviving.append((lot, remaining))
        active = surviving
        daily.append(Daily(
            date=day, demandQty=demand[day], incomingQty=sum(lot.quantity for lot in incoming[day]),
            closingQty=sum(quantity for _, quantity in active), unmetQty=unmet,
            expiringQty=expiring if expiry_known else None,
        ))
    return daily, expiry
