import json
import pytest
from pathlib import Path

from config.config_loader import _validate_raw_config_security, load_config


def test_docker_compose_binds_localhost_and_requires_bootstrap_token():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert "HUU_BOOTSTRAP_TOKEN: ${HUU_BOOTSTRAP_TOKEN:?" in compose


def test_desktop_uses_supported_electron_runtime():
    package = json.loads(Path("desktop/package.json").read_text(encoding="utf-8"))
    electron_version = package["devDependencies"]["electron"].lstrip("^~")
    builder_version = package["devDependencies"]["electron-builder"].lstrip("^~")

    assert tuple(map(int, electron_version.split("."))) >= (43, 1, 0)
    assert tuple(map(int, builder_version.split("."))) >= (26, 15, 3)
    assert package["build"]["electronVersion"] == electron_version


def test_config_rejects_plaintext_api_secret():
    with pytest.raises(ValueError, match="credential store"):
        _validate_raw_config_security({"crypto": {"mainnet": {"api_secret": "plain-secret"}}})


def test_config_allows_environment_placeholders():
    _validate_raw_config_security({"crypto": {"testnet": {"api_key": "${BINANCE_TESTNET_API_KEY}"}}})


def test_config_rejects_real_trading_enabled():
    with pytest.raises(ValueError, match="real_trading_enabled"):
        _validate_raw_config_security({"crypto": {"mainnet": {"real_trading_enabled": True}}})


def test_load_config_merges_missing_bundled_defaults(monkeypatch, tmp_path):
    bundled_dir = tmp_path / "bundled" / "config"
    bundled_dir.mkdir(parents=True)
    bundled_config = bundled_dir / "config.yaml"
    bundled_config.write_text(
        """
crypto:
  exchange: binance
ai:
  enabled: true
  provider: deepseek
  model: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY
risk:
  real_trading_enabled: false
storage:
  db_path: data/trading.db
""",
        encoding="utf-8",
    )
    runtime_config = tmp_path / "runtime" / "config.yaml"
    runtime_config.parent.mkdir()
    runtime_config.write_text(
        """
crypto:
  exchange: binance
risk:
  real_trading_enabled: false
""",
        encoding="utf-8",
    )
    overrides = tmp_path / "runtime_overrides.yaml"
    overrides.write_text("", encoding="utf-8")

    monkeypatch.setattr("config.config_loader.resource_path", lambda *parts: bundled_dir.parent.joinpath(*parts))
    monkeypatch.setattr("config.config_loader.get_runtime_overrides_path", lambda _config_path="": overrides)

    config = load_config(str(runtime_config))

    assert config["ai"]["enabled"] is True
    assert config["ai"]["model"] == "deepseek-v4-flash"


def test_load_config_keeps_user_override_when_merging_defaults(monkeypatch, tmp_path):
    bundled_dir = tmp_path / "bundled" / "config"
    bundled_dir.mkdir(parents=True)
    (bundled_dir / "config.yaml").write_text(
        """
ai:
  enabled: true
  model: deepseek-v4-flash
risk:
  real_trading_enabled: false
""",
        encoding="utf-8",
    )
    runtime_config = tmp_path / "runtime" / "config.yaml"
    runtime_config.parent.mkdir()
    runtime_config.write_text(
        """
ai:
  enabled: false
risk:
  real_trading_enabled: false
""",
        encoding="utf-8",
    )
    overrides = tmp_path / "runtime_overrides.yaml"
    overrides.write_text("", encoding="utf-8")

    monkeypatch.setattr("config.config_loader.resource_path", lambda *parts: bundled_dir.parent.joinpath(*parts))
    monkeypatch.setattr("config.config_loader.get_runtime_overrides_path", lambda _config_path="": overrides)

    config = load_config(str(runtime_config))

    assert config["ai"]["enabled"] is False
    assert config["ai"]["model"] == "deepseek-v4-flash"
