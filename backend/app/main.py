import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .data import Dataset
from .demo_data import load_demo
from .drafts import DraftStore, price_draft
from .replenishment import build_forecast
from .schemas import (
    DraftRequest, DraftResponse, ErrorBody, ErrorDetail, ErrorResponse, Forecast, Health, Stores,
)

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
    forecasts: dict[str, Forecast] = {}
    stores = Stores(stores=[])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        snapshot = dataset if dataset is not None else load_demo()
        database.initialize()
        forecasts.clear()
        forecasts.update({
            store.info.storeId: build_forecast(snapshot, store) for store in snapshot.stores
        })
        stores.stores = [store.info for store in snapshot.stores]
        yield

    app = FastAPI(title="Coyote Supply", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_ORIGINS,
        allow_methods=["GET", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.path_params.get("id") not in forecasts:
            return error("store_not_found")
        details = [
            ErrorDetail(
                path=".".join(str(part) for part in issue["loc"][1:]) or "body",
                reason=issue["type"],
            )
            for issue in exc.errors()
        ]
        return error("invalid_draft", details)

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
        return forecasts.get(id) or error("store_not_found")

    @app.get(
        "/api/stores/{id}/draft", response_model=DraftResponse, responses={404: {"model": ErrorResponse}},
    )
    def get_draft(id: str) -> DraftResponse | JSONResponse:
        if id not in forecasts:
            return error("store_not_found")
        return DraftResponse(storeId=id, draft=database.get(id))

    @app.put(
        "/api/stores/{id}/draft", response_model=DraftResponse,
        responses={status: {"model": ErrorResponse} for status in (404, 409, 422)},
    )
    def put_draft(id: str, request: DraftRequest) -> DraftResponse | JSONResponse:
        forecast = forecasts.get(id)
        if forecast is None:
            return error("store_not_found")
        if request.forecastId != forecast.forecastId:
            return error("stale_forecast")
        draft, details = price_draft(request, forecast)
        if details:
            return error("invalid_draft", details)
        database.replace(id, draft)
        return DraftResponse(storeId=id, draft=draft)

    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
