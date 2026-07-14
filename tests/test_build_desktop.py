from unittest.mock import MagicMock

from scripts import build_desktop


def test_ensure_electron_runtime_installs_missing_distribution(monkeypatch, tmp_path):
    desktop_dir = tmp_path / "desktop"
    installer = desktop_dir / "node_modules" / "electron" / "install.js"
    installer.parent.mkdir(parents=True)
    installer.write_text("", encoding="utf-8")
    run = MagicMock()

    monkeypatch.setattr(build_desktop, "DESKTOP_DIR", desktop_dir)
    monkeypatch.setattr(build_desktop, "run", run)

    build_desktop.ensure_electron_runtime()

    run.assert_called_once_with(["node", str(installer)], cwd=desktop_dir)


def test_ensure_electron_runtime_keeps_existing_distribution(monkeypatch, tmp_path):
    desktop_dir = tmp_path / "desktop"
    executable = desktop_dir / "node_modules" / "electron" / "dist" / "electron.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"electron")
    run = MagicMock()

    monkeypatch.setattr(build_desktop, "DESKTOP_DIR", desktop_dir)
    monkeypatch.setattr(build_desktop, "run", run)

    build_desktop.ensure_electron_runtime()

    run.assert_not_called()
