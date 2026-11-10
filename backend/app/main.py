import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .copilot import CopilotAnswer, CopilotQuestion, answer_question
from .data import Dataset
from .demo_data import load_dataset
from .drafts import DraftStore, price_draft
from .schemas import (
    DraftRequest, DraftResponse, ErrorBody, ErrorDetail, ErrorResponse, Forecast, Health, Stores,
)
from .shift import LossRejected, LossRequest, ShiftChanged, ShiftOverview, ShiftService, summarize_shift

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BACKEND / "data" / "drafts.sqlite3"
FRONTEND_DIST = BACKEND.parent / "frontend" / "dist"
LOCAL_ORIGINS = [
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 4173)
]
ERRORS = {
    "store_not_found": (404, "Точка не найдена."),
    "stale_forecast": (409, "Прогноз обновился. Сверьте черновик с новым расчётом."),
    "invalid_draft": (422, "Проверьте поля черновика."),
    "stale_shift": (409, "Смена обновилась. Сверьте остаток и повторите операцию."),
    "invalid_shift": (422, "Проверьте данные операции."),
}


def error(code: str, details: list[ErrorDetail] | None = None) -> JSONResponse:
    status, message = ERRORS[code]
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def create_app(
    db_path: Path | str | None = None, dataset: Dataset | None = None,
    frontend_dist: Path = FRONTEND_DIST,
) -> FastAPI:
    database = DraftStore(Path(db_path or os.getenv("COYOTE_DB_PATH") or DEFAULT_DB_PATH))
    shift: ShiftService
    stores = Stores(stores=[])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal shift
        snapshot = dataset if dataset is not None else load_dataset(os.getenv("COYOTE_DATASET_PATH"))
        database.initialize()
        shift = ShiftService(snapshot)
        with database.transaction(write=True) as connection:
            shift.initialize(connection)
        stores.stores = [store.info for store in snapshot.stores]
        yield

    app = FastAPI(title="Coyote", version="1.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_ORIGINS,
        allow_methods=["GET", "PUT", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.path_params.get("id") not in shift.stores:
            return error("store_not_found")
        details = [
            ErrorDetail(
                path=".".join(str(part) for part in issue["loc"][1:]) or "body",
                reason=issue["type"],
            )
            for issue in exc.errors()
        ]
        return error("invalid_shift" if "/shift/" in request.url.path else "invalid_draft", details)

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health()

    @app.get("/api/stores", response_model=Stores)
    def list_stores() -> Stores:
        return stores

    @app.get(
        "/api/stores/{id}/forecast", response_model=Forecast, responses={404: {"model": ErrorResponse}},
    )
    def get_forecast(id: str) -> Forecast | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        with database.transaction() as connection:
            return shift.current(connection, id).forecast

    @app.get(
        "/api/stores/{id}/draft", response_model=DraftResponse, responses={404: {"model": ErrorResponse}},
    )
    def get_draft(id: str) -> DraftResponse | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        with database.transaction() as connection:
            return DraftResponse(storeId=id, draft=database.get(connection, id))

    @app.put(
        "/api/stores/{id}/draft", response_model=DraftResponse,
        responses={status: {"model": ErrorResponse} for status in (404, 409, 422)},
    )
    def put_draft(id: str, request: DraftRequest) -> DraftResponse | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        with database.transaction(write=True) as connection:
            forecast = shift.current(connection, id).forecast
            if request.forecastId != forecast.forecastId:
                return error("stale_forecast")
            draft, details = price_draft(request, forecast)
            if details:
                return error("invalid_draft", details)
            database.replace(connection, id, draft)
            return DraftResponse(storeId=id, draft=draft)

    @app.get(
        "/api/stores/{id}/shift", response_model=ShiftOverview,
        responses={404: {"model": ErrorResponse}},
    )
    def get_shift(id: str) -> ShiftOverview | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        with database.transaction() as connection:
            return summarize_shift(shift.current(connection, id), database.get(connection, id))

    @app.post(
        "/api/stores/{id}/shift/losses", response_model=ShiftOverview,
        responses={status: {"model": ErrorResponse} for status in (404, 409, 422)},
    )
    def post_loss(id: str, request: LossRequest) -> ShiftOverview | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        try:
            with database.transaction(write=True) as connection:
                snapshot = shift.record(connection, id, request)
                return summarize_shift(snapshot, database.get(connection, id))
        except ShiftChanged:
            return error("stale_shift")
        except LossRejected as exc:
            return error("invalid_shift", [ErrorDetail(path=exc.path, reason=exc.reason)])

    @app.post(
        "/api/stores/{id}/shift/copilot", response_model=CopilotAnswer,
        responses={status: {"model": ErrorResponse} for status in (404, 422)},
    )
    def ask_copilot(id: str, request: CopilotQuestion) -> CopilotAnswer | JSONResponse:
        if id not in shift.stores:
            return error("store_not_found")
        with database.transaction() as connection:
            overview = summarize_shift(shift.current(connection, id), database.get(connection, id))
        return answer_question(shift.dataset, overview, request.question)

    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
