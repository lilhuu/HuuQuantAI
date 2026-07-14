"""FastAPI entrypoint for the crypto-only desktop API."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.dependencies import get_api_settings, get_crypto_service, get_current_user
from api.error_codes import ErrorCode, default_error_code_for_status
from api.models.response import HealthCheckResponse
from api.routers import auth, crypto, crypto_ws
from api.services.observability import api_metrics
from core.desktop_paths import resource_path
from core.sqlite_utils import configure_sqlite_connection


settings = get_api_settings()
app_settings = settings["app"]
cors_settings = settings["cors"]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = resource_path("frontend", "dist")
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

openapi_tags = [
    {"name": "auth", "description": "Local authentication and preferences."},
    {"name": "crypto", "description": "Binance public data and local crypto paper trading."},
    {"name": "health", "description": "API health checks."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    service = get_crypto_service()
    service.start_background_tasks()
    try:
        yield
    finally:
        await service.shutdown_background_tasks()


app = FastAPI(
    title=app_settings["title"],
    version=app_settings["version"],
    description=app_settings.get("description"),
    docs_url=app_settings["docs_url"],
    redoc_url=app_settings["redoc_url"],
    openapi_url=app_settings["openapi_url"],
    lifespan=lifespan,
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings["allow_origins"],
    allow_credentials=cors_settings["allow_credentials"],
    allow_methods=cors_settings["allow_methods"],
    allow_headers=cors_settings["allow_headers"],
)

app.mount(
    "/assets",
    StaticFiles(directory=str(FRONTEND_ASSETS), check_dir=False),
    name="frontend-assets",
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    api_metrics.request_started()
    start = perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = int(getattr(response, "status_code", 500) or 500)
    except Exception:
        duration_ms = (perf_counter() - start) * 1000
        api_metrics.request_finished(duration_ms, status_code)
        raise

    duration_ms = (perf_counter() - start) * 1000
    api_metrics.request_finished(duration_ms, status_code)
    response.headers["X-Request-Time-Ms"] = f"{duration_ms:.2f}"
    return response


protected_dependencies = [Depends(get_current_user)]

app.include_router(auth.router, prefix="/api/v1")
app.include_router(crypto.router, prefix="/api/v1", dependencies=protected_dependencies)
app.include_router(crypto_ws.router)


@app.get("/", include_in_schema=False)
async def root():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {
        "message": "HUU Crypto Quant API is running.",
        "hint": "Build the frontend first with npm.cmd run build in the frontend directory.",
    }


@app.get(
    "/healthz",
    response_model=HealthCheckResponse,
    tags=["health"],
    summary="Health check",
)
async def healthz() -> HealthCheckResponse:
    service = get_crypto_service()
    storage_check = _check_sqlite_storage(service)
    trading_check = _check_trading_system(service)
    data_check = _check_market_data(service)

    storage_ok = bool(storage_check.get("ok"))
    trading_ok = bool(trading_check.get("ok"))
    data_ok = bool(data_check.get("ok"))
    cache_available = bool(data_check.get("cache_available"))
    if storage_ok and trading_ok and data_ok:
        status = "ok"
    elif storage_ok and trading_ok and cache_available:
        status = "degraded"
    else:
        status = "error"

    return HealthCheckResponse(
        status=status,
        timestamp=datetime.now().isoformat(),
        api_version=str(app.version),
        trading_system_running=trading_ok,
        data_feed_connected=data_ok,
        checks={
            "sqlite": storage_check,
            "trading": trading_check,
            "market_data": data_check,
        },
    )


def _check_sqlite_storage(service: Any) -> dict[str, Any]:
    """Run a lightweight SQLite health check against the configured runtime DB."""
    db_path = (
        getattr(getattr(service, "paper_broker", None), "storage_path", None)
        or getattr(getattr(service, "market_cache", None), "db_path", None)
        or "data/trading.db"
    )
    try:
        path = Path(str(db_path)).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=30) as conn:
            configure_sqlite_connection(conn)
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            conn.execute("SELECT 1").fetchone()
        message = str(quick_check[0] if quick_check else "ok")
        return {"ok": message.lower() == "ok", "engine": "sqlite", "path": str(path), "message": message}
    except Exception as exc:
        return {"ok": False, "engine": "sqlite", "path": str(db_path), "message": str(exc)}


def _check_trading_system(service: Any) -> dict[str, Any]:
    broker = getattr(service, "paper_broker", None)
    account = {}
    try:
        if broker is not None and hasattr(broker, "get_account_info"):
            account = broker.get_account_info()
    except Exception as exc:
        return {"ok": False, "mode": "crypto_paper", "message": str(exc)}
    real_enabled = bool(account.get("real_trading_enabled", False))
    connected = bool(getattr(broker, "is_connected", True))
    return {
        "ok": connected and not real_enabled,
        "mode": "crypto_paper",
        "paper_broker_connected": connected,
        "real_trading_enabled": real_enabled,
        "message": "paper broker ready" if connected and not real_enabled else "paper broker not ready",
    }


def _check_market_data(service: Any) -> dict[str, Any]:
    symbol = (getattr(service, "default_symbols", None) or ["BTC/USDT"])[0]
    try:
        rows = service.provider.fetch_quotes([symbol])
        if rows:
            return {
                "ok": True,
                "symbol": symbol,
                "source": str(rows[0].get("source", getattr(service.provider, "exchange_id", "binance"))),
                "cache_available": True,
                "message": "live quote available",
            }
        return {"ok": False, "symbol": symbol, "cache_available": False, "message": "live quote returned no rows"}
    except Exception as exc:
        cache_rows = []
        try:
            cache_rows = service.market_cache.get_quotes([symbol])
        except Exception:
            cache_rows = []
        return {
            "ok": False,
            "symbol": symbol,
            "source": "cache_binance" if cache_rows else "unavailable",
            "cache_available": bool(cache_rows),
            "message": f"live quote unavailable: {exc}",
        }


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def missing_api_route(full_path: str):
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_spa_fallback(full_path: str):
    reserved_prefixes = (
        "api/",
        "ws/",
        "assets/",
        "docs",
        "redoc",
        "openapi.json",
        "healthz",
    )
    if full_path.startswith(reserved_prefixes):
        raise HTTPException(status_code=404, detail="Not found")
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    raise HTTPException(status_code=404, detail="Frontend build not found")


def _build_error_response(
    status_code: int,
    message: str,
    *,
    error_code: str,
    error_id: str | None = None,
    errors: list[dict] | None = None,
) -> JSONResponse:
    payload = {
        "success": False,
        "message": message,
        "error_code": error_code,
        "error_id": error_id or str(uuid4()),
    }
    if errors:
        payload["errors"] = errors
    return JSONResponse(status_code=status_code, content=payload)


@app.exception_handler(HTTPException)
async def fastapi_http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        detail = str(exc.detail.get("message") or "Request failed")
        error_code = str(exc.detail.get("error_code") or default_error_code_for_status(exc.status_code))
    else:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        error_code = default_error_code_for_status(exc.status_code)
    return _build_error_response(
        exc.status_code,
        detail,
        error_code=error_code,
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _build_error_response(
        exc.status_code,
        detail,
        error_code=default_error_code_for_status(exc.status_code),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return _build_error_response(
        422,
        "Request validation failed.",
        error_code=ErrorCode.VALIDATION_FAILED,
        errors=exc.errors(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return _build_error_response(
        500,
        str(exc) or "Internal server error.",
        error_code=ErrorCode.INTERNAL_SERVER_ERROR,
    )
