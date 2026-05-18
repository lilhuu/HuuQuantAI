"""FastAPI entrypoint for the crypto-only desktop API."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.dependencies import get_api_settings, get_current_user
from api.error_codes import ErrorCode, default_error_code_for_status
from api.models.response import HealthCheckResponse
from api.routers import auth, crypto, crypto_ws
from api.services.observability import api_metrics
from core.desktop_paths import resource_path


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
    yield


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
    return HealthCheckResponse(
        status="ok",
        timestamp=datetime.now().isoformat(),
        api_version=str(app.version),
        trading_system_running=True,
        data_feed_connected=True,
    )


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
