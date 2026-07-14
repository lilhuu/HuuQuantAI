"""Build the Windows desktop app: Vue dist, PyInstaller backend, Electron portable exe."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DESKTOP_DIR = PROJECT_ROOT / "desktop"
RELEASE_EXE = PROJECT_ROOT / "release" / "HUU Auto Trade Console.exe"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def npm_command() -> str:
    return "npm.cmd" if platform.system().lower().startswith("win") else "npm"


def run(command: list[str], *, cwd: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n> {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def ensure_node_dependencies() -> None:
    npm = npm_command()
    if not command_exists(npm):
        raise RuntimeError("未找到 npm，请先安装 Node.js。")

    if not (FRONTEND_DIR / "node_modules").exists():
        run([npm, "install"], cwd=FRONTEND_DIR)

    if not (DESKTOP_DIR / "node_modules").exists():
        run([npm, "install"], cwd=DESKTOP_DIR)


def ensure_electron_runtime() -> None:
    executable_name = "electron.exe" if platform.system().lower().startswith("win") else "electron"
    electron_dir = DESKTOP_DIR / "node_modules" / "electron"
    if (electron_dir / "dist" / executable_name).exists():
        return

    installer = electron_dir / "install.js"
    if not installer.exists():
        raise RuntimeError("Electron 安装器缺失，请在 desktop 目录重新运行 npm install。")
    run(["node", str(installer)], cwd=DESKTOP_DIR)


def build_frontend() -> None:
    run([npm_command(), "run", "build"], cwd=FRONTEND_DIR)


def build_backend() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "当前虚拟环境缺少 PyInstaller。请先运行："
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "desktop_backend.spec",
            "--noconfirm",
            "--clean",
            "--distpath",
            "dist/desktop-backend",
            "--workpath",
            "build/desktop-backend",
        ],
        cwd=PROJECT_ROOT,
    )


def build_electron() -> None:
    run([npm_command(), "run", "dist"], cwd=DESKTOP_DIR)


def main() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("ELECTRON_MIRROR", "https://npmmirror.com/mirrors/electron/")
    os.environ.setdefault(
        "ELECTRON_BUILDER_BINARIES_MIRROR",
        "https://npmmirror.com/mirrors/electron-builder-binaries/",
    )

    ensure_node_dependencies()
    ensure_electron_runtime()
    build_frontend()
    build_backend()
    build_electron()

    print("\n桌面应用构建完成。")
    print(f"输出文件: {RELEASE_EXE}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\n构建停止: {exc}")
        sys.exit(1)
