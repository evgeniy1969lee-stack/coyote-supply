from collections import defaultdict
from datetime import date, time
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from .schemas import ContractModel, Id, PositiveQty, Qty, StoreInfo, Unit


class Ingredient(ContractModel):
    name: str
    unit: Unit
    pack_qty: PositiveQty
    pack_price_kzt: Qty
    track_expiry: bool = True


class Recipe(ContractModel):
    sku: Id
    valid_from: date
    valid_until: date | None = None  # Exclusive.
    usage: dict[Id, PositiveQty]


class Sale(ContractModel):
    id: Id
    sku: Id
    at: AwareDatetime
    quantity: PositiveQty
    status: Literal["completed", "cancelled", "refunded"] = "completed"


class Lot(ContractModel):
    id: Id
    quantity: PositiveQty
    expires_on: date | None = None


class Delivery(ContractModel):
    ingredient_id: Id
    arrives_on: date
    lot: Lot
    confirmed: bool = True

    @model_validator(mode="after")
    def check_expiry(self) -> Self:
        if self.lot.expires_on is not None and self.lot.expires_on < self.arrives_on:
            raise ValueError("Delivery lot expires before arrival")
        return self


class Inventory(ContractModel):
    on_hand: Qty | None
    observed_at: AwareDatetime
    lots: list[Lot] | None = None
    safety_stock: Qty = 0
    max_stock: Qty

    @model_validator(mode="after")
    def check_stock(self) -> Self:
        if self.lots is not None and sum(lot.quantity for lot in self.lots) != self.on_hand:
            raise ValueError("Inventory lot quantities must sum to on-hand quantity")
        if self.max_stock < self.safety_stock:
            raise ValueError("Maximum stock must cover safety stock")
        return self


class DeliveryRule(ContractModel):
    weekday: Annotated[int, Field(strict=True, ge=0, le=6)]  # Monday is 0.
    lead_days: Annotated[int, Field(strict=True, ge=1, le=7)]
    deadline_time: time

    @model_validator(mode="after")
    def check_local_time(self) -> Self:
        if self.deadline_time.tzinfo is not None:
            raise ValueError("Delivery deadlines must use local wall time")
        return self


Observation = Literal["complete", "missing", "stockout"]


class StoreData(ContractModel):
    info: StoreInfo
    max_inventory_age_hours: PositiveQty
    calendar: list[DeliveryRule]
    inventory: dict[Id, Inventory]
    deliveries: list[Delivery]
    observations: dict[date, Observation]
    sales: list[Sale]

    @property
    def as_of_date(self) -> date:
        return self.info.asOf.astimezone(ZoneInfo(self.info.timeZone)).date()

    @model_validator(mode="after")
    def check_store(self) -> Self:
        ZoneInfo(self.info.timeZone)
        if len({rule.weekday for rule in self.calendar}) != len(self.calendar):
            raise ValueError("Duplicate delivery weekday")
        if any(stock.observed_at > self.info.asOf for stock in self.inventory.values()):
            raise ValueError("Inventory snapshot is later than the forecast cutoff")
        if any(delivery.ingredient_id not in self.inventory for delivery in self.deliveries):
            raise ValueError("Delivery references an ingredient outside the store")
        lot_ids = [lot.id for stock in self.inventory.values() for lot in stock.lots or []]
        lot_ids.extend(delivery.lot.id for delivery in self.deliveries)
        if len(set(lot_ids)) != len(lot_ids):
            raise ValueError("Duplicate lot ID")
        sales_by_id: dict[str, Sale] = {}
        for sale in self.sales:
            if sales_by_id.setdefault(sale.id, sale) != sale:
                raise ValueError("Conflicting sales with the same ID")
        return self


class Dataset(ContractModel):
    version: Id
    data_mode: Literal["synthetic", "imported"] = "synthetic"
    catalog: dict[Id, Ingredient]
    recipes: list[Recipe]
    stores: list[StoreData]

    @model_validator(mode="after")
    def check_references(self) -> Self:
        if len({store.info.storeId for store in self.stores}) != len(self.stores):
            raise ValueError("Duplicate store ID")
        if any(store.inventory.keys() - self.catalog.keys() for store in self.stores):
            raise ValueError("Store inventory references an unknown ingredient")
        by_sku: dict[str, list[Recipe]] = defaultdict(list)
        for recipe in self.recipes:
            if recipe.usage.keys() - self.catalog.keys():
                raise ValueError("Recipe references an unknown ingredient")
            if recipe.valid_until is not None and recipe.valid_until <= recipe.valid_from:
                raise ValueError("Empty recipe interval")
            by_sku[recipe.sku].append(recipe)
        for versions in by_sku.values():
            ordered = sorted(versions, key=lambda recipe: recipe.valid_from)
            for older, newer in zip(ordered, ordered[1:]):
                if older.valid_until is None or older.valid_until > newer.valid_from:
                    raise ValueError("Overlapping recipe versions")
        return self
