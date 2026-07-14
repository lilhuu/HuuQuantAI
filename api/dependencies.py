"""Dependency helpers for the API layer."""

import asyncio
from datetime import datetime
from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import yaml

from api.error_codes import ApiError, ErrorCode

from api.services.auth_service import AuthService
from api.services.crypto_service import CryptoService
from config.config_loader import load_config as load_trading_config
from core.desktop_paths import (
    get_api_config_path,
    get_trading_config_path,
    is_desktop_mode,
    resolve_writable_path,
)


DEFAULT_API_SETTINGS: Dict[str, Any] = {
    "app": {
        "title": "HuuQuantAI API",
        "version": "0.1.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
    },
    "cors": {
        "allow_origins": [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    },
    "trading": {
        "config_path": "config/config.yaml",
        "auto_start": False,
        "stop_on_shutdown": True,
    },
    "auth": {
        "storage_path": "data/app_state.db",
        "session_hours": 168,
    },
    "websocket": {
        "auth_timeout_seconds": 5,
        "orders_interval_seconds": 1.0,
        "system_interval_seconds": 1.0,
    },
}


bearer_scheme = HTTPBearer(auto_error=False)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def get_api_settings() -> Dict[str, Any]:
    """Load API settings from config/api_config.yaml."""
    path = get_api_config_path()
    if not path.exists():
        settings = DEFAULT_API_SETTINGS
    else:
        with path.open("r", encoding="utf-8") as file_obj:
            loaded = yaml.safe_load(file_obj) or {}
        settings = _deep_merge(DEFAULT_API_SETTINGS, loaded)

    if is_desktop_mode():
        settings = _apply_desktop_overrides(settings)
    return settings


def _apply_desktop_overrides(settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(settings)
    server = dict(merged.get("server", {}))
    server["host"] = os.getenv("AUTO_TRADER_HOST", "127.0.0.1")
    if os.getenv("AUTO_TRADER_PORT"):
        server["port"] = int(os.getenv("AUTO_TRADER_PORT", "0"))
    merged["server"] = server

    trading = dict(merged.get("trading", {}))
    trading["config_path"] = str(get_trading_config_path())
    merged["trading"] = trading

    auth = dict(merged.get("auth", {}))
    auth["storage_path"] = str(resolve_writable_path(auth.get("storage_path", "data/app_state.db"), default_relative="data/app_state.db"))
    merged["auth"] = auth

    cors = dict(merged.get("cors", {}))
    origins = list(cors.get("allow_origins", []))
    current_origin = f"http://127.0.0.1:{server.get('port', 8000)}"
    if current_origin not in origins:
        origins.append(current_origin)
    cors["allow_origins"] = origins
    merged["cors"] = cors
    return merged


_CRYPTO_SERVICE_CACHE: Optional[CryptoService] = None


def get_crypto_service() -> CryptoService:
    """Return the singleton crypto service used by the API."""
    global _CRYPTO_SERVICE_CACHE
    if _CRYPTO_SERVICE_CACHE is None:
        settings = get_api_settings()
        config_path = settings.get("trading", {}).get("config_path", "config/config.yaml")
        _CRYPTO_SERVICE_CACHE = CryptoService(load_trading_config(config_path))
    return _CRYPTO_SERVICE_CACHE


def _clear_crypto_service_cache() -> None:
    global _CRYPTO_SERVICE_CACHE
    _CRYPTO_SERVICE_CACHE = None


get_crypto_service.cache_clear = _clear_crypto_service_cache


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """Return the singleton auth service used by the API."""
    settings = get_api_settings()
    auth_settings = settings.get("auth", {})
    return AuthService(
        storage_path=auth_settings.get("storage_path", "data/app_state.db"),
        session_hours=auth_settings.get("session_hours", 168),
        bootstrap_token=os.getenv("HUU_BOOTSTRAP_TOKEN", ""),
    )


def _extract_bearer_token(credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if credentials is None:
        return None
    if str(credentials.scheme).lower() != "bearer":
        return None
    token = str(credentials.credentials or "").strip()
    return token or None


async def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """Return the current user when a valid bearer token is present."""
    token = _extract_bearer_token(credentials)
    if token is None:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip() or None

    if token is None:
        return None
    return get_auth_service().authenticate_token(token)


async def get_current_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """Return the current bearer token string."""
    token = _extract_bearer_token(credentials)
    if token is None:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip() or None

    if token is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "请先登录后再访问",
            ErrorCode.AUTH_REQUIRED,
        )
    return token


async def get_current_user(user=Depends(get_optional_current_user)):
    """Require a valid logged-in user."""
    if user is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "请先登录后再访问",
            ErrorCode.AUTH_REQUIRED,
        )
    return user


async def authenticate_websocket(websocket: WebSocket):
    """Authenticate a websocket connection using a first-frame auth message."""
    timeout_seconds = float(
        get_api_settings().get("websocket", {}).get("auth_timeout_seconds", 5) or 5
    )

    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=max(timeout_seconds, 0.1))
    except asyncio.TimeoutError as exc:
        await websocket.close(code=4408, reason="websocket authentication timeout")
        raise RuntimeError("websocket authentication timeout") from exc
    except Exception as exc:
        try:
            await websocket.close(code=4401, reason="websocket authentication failed")
        except Exception:
            pass
        raise RuntimeError("websocket authentication failed") from exc

    if not isinstance(message, dict) or str(message.get("action", "")).strip().lower() != "auth":
        await websocket.close(code=4401, reason="websocket authentication required")
        raise RuntimeError("websocket authentication required")

    token = str(message.get("token", "") or "").strip()
    user = get_auth_service().authenticate_token(token)
    if user is None:
        await websocket.close(code=4401, reason="websocket authentication failed")
        raise RuntimeError("websocket authentication failed")

    await websocket.send_json(
        {
            "type": "auth_ok",
            "timestamp": datetime.now().isoformat(),
        }
    )
    return user
