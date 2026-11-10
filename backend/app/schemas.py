from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

MAX_SAFE_INTEGER = 2**53 - 1
Qty = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
PositiveQty = Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE_INTEGER)]
Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]
Unit = Literal["ml", "g", "pcs"]
DataIssue = Literal[
    "missing_on_hand", "stale_on_hand", "insufficient_history", "missing_recipe",
    "missing_schedule", "unknown_lot_expiry",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(ContractModel):
    status: Literal["ok"] = "ok"


class StoreInfo(ContractModel):
    storeId: Id
    name: str
    timeZone: str
    asOf: AwareDatetime


class Stores(ContractModel):
    stores: list[StoreInfo]


class Schedule(ContractModel):
    orderDeadlineAt: AwareDatetime
    arrivalDate: date
    nextArrivalDate: date


class Daily(ContractModel):
    date: date
    demandQty: Qty
    incomingQty: Qty
    closingQty: Qty
    unmetQty: Qty
    expiringQty: Qty | None


class Stockout(ContractModel):
    type: Literal["stockout"] = "stockout"
    date: date
    firstUnmetQty: PositiveQty
    quantity: PositiveQty


class Excess(ContractModel):
    type: Literal["excess"] = "excess"
    date: date
    quantity: PositiveQty


class Expiry(ContractModel):
    type: Literal["expiry"] = "expiry"
    date: date
    quantity: PositiveQty
    lotId: Id


class InsufficientData(ContractModel):
    type: Literal["insufficient_data"] = "insufficient_data"
    reason: DataIssue


Risk = Annotated[Stockout | Excess | Expiry | InsufficientData, Field(discriminator="type")]


class Explanation(ContractModel):
    demandBeforeArrivalQty: Qty
    shortageBeforeArrivalQty: Qty
    uncoveredWindowDemandQty: Qty
    safetyStockQty: Qty
    endStockWithoutOrderQty: Qty
    unroundedOrderQty: Qty


class IngredientForecast(ContractModel):
    ingredientId: Id
    name: str
    unit: Unit
    onHandQty: Qty | None
    daily: list[Daily]
    risks: list[Risk]
    recommendedQty: Qty | None
    packQty: PositiveQty
    packPriceKzt: Qty
    explanation: Explanation | None
    dataStatus: Literal["ok", "needs_review"]


class Forecast(ContractModel):
    storeId: Id
    forecastId: Id
    dataMode: Literal["synthetic", "imported"] = "synthetic"
    asOf: AwareDatetime
    schedule: Schedule | None
    ingredients: list[IngredientForecast]


class DraftInputRow(ContractModel):
    ingredientId: Id
    quantity: PositiveQty


class DraftRequest(ContractModel):
    forecastId: Id
    rows: list[DraftInputRow]


class DraftRow(DraftInputRow):
    packCount: PositiveQty
    packPriceKzt: Qty
    lineTotalKzt: Qty


class Draft(ContractModel):
    forecastId: Id
    rows: Annotated[list[DraftRow], Field(min_length=1)]
    totalKzt: Qty
    savedAt: AwareDatetime


class DraftResponse(ContractModel):
    storeId: Id
    draft: Draft | None


class ErrorDetail(ContractModel):
    path: str
    reason: str


class ErrorBody(ContractModel):
    code: Literal["store_not_found", "stale_forecast", "invalid_draft", "stale_shift", "invalid_shift"]
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(ContractModel):
    error: ErrorBody
