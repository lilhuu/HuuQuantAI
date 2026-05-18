"""Configuration loader utilities."""

from pathlib import Path
import yaml


BASE_DIR = Path(__file__).resolve().parent


def load_yaml(name: str) -> dict:
    """Load a YAML file from the config directory."""
    path = BASE_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
