"""Configuration loading helpers."""

from pathlib import Path
from typing import Dict

import yaml

from core.credential_manager import resolve_env_placeholders
from core.desktop_paths import (
    apply_desktop_trading_config_paths,
    get_runtime_overrides_path as get_desktop_runtime_overrides_path,
)
from core.file_lock import read_text_locked


_SENSITIVE_KEYS = {"api_key", "api_secret", "secret", "password", "pass"}
_ENV_PLACEHOLDER_PREFIX = "${"


def _deep_merge(base: Dict, override: Dict) -> Dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_raw_config_security(config: Dict, path: tuple[str, ...] = ()) -> None:
    for key, value in config.items():
        key_text = str(key)
        key_lower = key_text.lower()
        current_path = (*path, key_text)
        if isinstance(value, dict):
            _validate_raw_config_security(value, current_path)
            continue
        if key_lower == "real_trading_enabled" and bool(value):
            raise ValueError(f"Unsafe config: {'.'.join(current_path)} must not be enabled in config.yaml")
        if key_lower in _SENSITIVE_KEYS and _is_plain_secret(value):
            raise ValueError(f"Unsafe config: {'.'.join(current_path)} must use an environment variable or credential store")


def _is_plain_secret(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return not (text.startswith(_ENV_PLACEHOLDER_PREFIX) and text.endswith("}"))


def get_runtime_overrides_path(config_path: str = "config/config.yaml") -> Path:
    """Return the runtime override config path."""
    return get_desktop_runtime_overrides_path()


def load_config(config_path: str = "config/config.yaml") -> Dict:
    """Load YAML config, apply runtime overrides, and resolve env placeholders."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with path.open("r", encoding="utf-8") as file_obj:
        config = yaml.safe_load(file_obj) or {}

    overrides_path = get_runtime_overrides_path(config_path)
    overrides_content = read_text_locked(overrides_path, default="") or ""
    if overrides_content.strip():
        overrides = yaml.safe_load(overrides_content) or {}
        config = _deep_merge(config, overrides)

    _validate_raw_config_security(config)
    resolved = resolve_env_placeholders(config)
    return apply_desktop_trading_config_paths(resolved)
