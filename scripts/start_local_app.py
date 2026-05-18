"""Build the frontend if needed, then start the local integrated app."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Dict

import uvicorn
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"

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


def newest_mtime(paths: list[Path]) -> float:
    """Return the newest modified time under files/directories."""
    newest = 0.0
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
            continue
        for child in path.rglob("*"):
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
    return newest


def should_build_frontend(force: bool = False) -> bool:
    """Build when dist is missing or frontend source is newer than dist."""
    if force or not FRONTEND_DIST_INDEX.exists():
        return True

    dist_mtime = FRONTEND_DIST_INDEX.stat().st_mtime
    source_mtime = newest_mtime(
        [
            FRONTEND_DIR / "src",
            FRONTEND_DIR / "index.html",
            FRONTEND_DIR / "package.json",
            FRONTEND_DIR / "vite.config.js",
        ]
    )
    return source_mtime > dist_mtime


def build_frontend(force: bool = False) -> None:
    """Run the production frontend build when needed."""
    if not should_build_frontend(force):
        print("前端构建已是最新，跳过 npm build。")
        return

    npm_command = "npm.cmd" if platform.system().lower().startswith("win") else "npm"
    print("正在构建前端生产包...")
    subprocess.run([npm_command, "run", "build"], cwd=FRONTEND_DIR, check=True)


def main() -> None:
    """Start the integrated local web app."""
    parser = argparse.ArgumentParser(description="启动本地一体化交易应用")
    parser.add_argument("--skip-build", action="store_true", help="跳过前端构建检查")
    parser.add_argument("--force-build", action="store_true", help="强制重新构建前端")
    args = parser.parse_args()

    if not args.skip_build:
        build_frontend(force=args.force_build)

    settings = load_api_settings()
    server = settings.get("server", {})
    host = server.get("host", "127.0.0.1")
    port = int(server.get("port", 8000))

    print(f"本地一体化应用启动中: http://{host}:{port}")
    uvicorn.run(
        "api.main:app",
        app_dir=str(PROJECT_ROOT),
        host=host,
        port=port,
        reload=bool(server.get("reload", False)),
    )


if __name__ == "__main__":
    main()
