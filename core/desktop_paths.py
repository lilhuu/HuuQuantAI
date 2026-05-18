"""Path helpers for source, PyInstaller, and Electron desktop modes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict


APP_NAME = "AutoTrader"


def is_desktop_mode() -> bool:
    """Return True when the backend is launched by the desktop shell."""
    return os.getenv("AUTO_TRADER_DESKTOP", "").strip() == "1"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Return the read-only application resource root."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    """Resolve a bundled or source-tree resource path."""
    return resource_root().joinpath(*parts)


def app_data_dir() -> Path:
    """Return the writable application data directory."""
    explicit = os.getenv("AUTO_TRADER_APP_DATA_DIR", "").strip()
    if explicit:
        base = Path(explicit)
    elif os.name == "nt":
        base = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    else:
        base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def app_config_dir() -> Path:
    path = app_data_dir() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_writable_path(value: str | os.PathLike[str], *, default_relative: str) -> Path:
    """Resolve a writable path, mapping relative desktop paths into AppData."""
    raw = Path(value or default_relative)
    if raw.is_absolute():
        raw.parent.mkdir(parents=True, exist_ok=True)
        return raw
    if is_desktop_mode():
        resolved = app_data_dir() / raw
    else:
        resolved = Path(raw)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_desktop_config(filename: str) -> Path:
    """Copy one bundled default config into AppData on first desktop launch."""
    destination = app_config_dir() / filename
    if destination.exists():
        return destination

    source = resource_path("config", filename)
    if source.exists():
        shutil.copy2(source, destination)
    return destination


def get_api_config_path() -> Path:
    explicit = os.getenv("AUTO_TRADER_API_CONFIG", "").strip()
    if explicit:
        return Path(explicit)
    if is_desktop_mode():
        return ensure_desktop_config("api_config.yaml")
    return resource_path("config", "api_config.yaml")


def get_trading_config_path() -> Path:
    explicit = os.getenv("AUTO_TRADER_CONFIG", "").strip()
    if explicit:
        return Path(explicit)
    if is_desktop_mode():
        return ensure_desktop_config("config.yaml")
    return resource_path("config", "config.yaml")


def get_runtime_overrides_path() -> Path:
    explicit = os.getenv("AUTO_TRADER_RUNTIME_OVERRIDES", "").strip()
    if explicit:
        return Path(explicit)

    filename = "runtime_overrides.test.yaml" if os.getenv("PYTEST_CURRENT_TEST") else "runtime_overrides.yaml"
    base_dir = app_data_dir() / "data" if is_desktop_mode() else Path("data")
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / filename


def apply_desktop_trading_config_paths(config: Dict[str, Any]) -> Dict[str, Any]:
    """Route writable trading config paths into AppData during desktop mode."""
    if not is_desktop_mode():
        return config

    storage = config.setdefault("storage", {})
    storage["db_path"] = str(resolve_writable_path(storage.get("db_path", "data/trading.db"), default_relative="data/trading.db"))

    database = config.setdefault("database", {})
    if str(database.get("engine", "sqlite")).strip().lower() == "sqlite":
        database["sqlite_path"] = str(
            resolve_writable_path(database.get("sqlite_path", storage["db_path"]), default_relative="data/trading.db")
        )

    csv_path = storage.get("csv_path")
    if csv_path:
        storage["csv_path"] = str(resolve_writable_path(csv_path, default_relative="data/quotes.csv"))

    return config


def ensure_desktop_environment() -> None:
    """Create desktop AppData directories and default config files."""
    if not is_desktop_mode():
        return
    app_data_dir()
    app_logs_dir()
    ensure_desktop_config("api_config.yaml")
    ensure_desktop_config("config.yaml")
