"""Desktop backend entry point used by Electron and PyInstaller."""

from __future__ import annotations

import logging
import os

import uvicorn

from core.desktop_paths import app_logs_dir, ensure_desktop_environment


def setup_desktop_logging() -> None:
    """Write backend logs into the desktop AppData log directory."""
    log_dir = app_logs_dir()
    log_file = log_dir / "backend.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    """Start the FastAPI backend in desktop mode."""
    os.environ.setdefault("AUTO_TRADER_DESKTOP", "1")
    os.environ.setdefault("AUTO_TRADER_HOST", "127.0.0.1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    ensure_desktop_environment()
    setup_desktop_logging()

    host = os.getenv("AUTO_TRADER_HOST", "127.0.0.1")
    port = int(os.getenv("AUTO_TRADER_PORT", "8000"))
    logging.getLogger(__name__).info("Starting desktop backend on http://%s:%s", host, port)

    from api.main import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
