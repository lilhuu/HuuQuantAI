"""Convenience launcher for the FastAPI service."""

from pathlib import Path
import sys
from typing import Any, Dict

import uvicorn
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_api_settings(config_path: str = "config/api_config.yaml") -> Dict[str, Any]:
    """Load API server settings."""
    path = PROJECT_ROOT / config_path
    if not path.exists():
        return {
            "server": {
                "host": "127.0.0.1",
                "port": 8000,
                "reload": False,
            }
        }

    with path.open("r", encoding="utf-8") as file_obj:
        return yaml.safe_load(file_obj) or {}


def main() -> None:
    """Start the FastAPI app with uvicorn."""
    settings = load_api_settings()
    server = settings.get("server", {})
    uvicorn.run(
        "api.main:app",
        app_dir=str(PROJECT_ROOT),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8000)),
        reload=bool(server.get("reload", False)),
    )


if __name__ == "__main__":
    main()
