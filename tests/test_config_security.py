import pytest

from config.config_loader import _validate_raw_config_security


def test_config_rejects_plaintext_api_secret():
    with pytest.raises(ValueError, match="credential store"):
        _validate_raw_config_security({"crypto": {"mainnet": {"api_secret": "plain-secret"}}})


def test_config_allows_environment_placeholders():
    _validate_raw_config_security({"crypto": {"testnet": {"api_key": "${BINANCE_TESTNET_API_KEY}"}}})


def test_config_rejects_real_trading_enabled():
    with pytest.raises(ValueError, match="real_trading_enabled"):
        _validate_raw_config_security({"crypto": {"mainnet": {"real_trading_enabled": True}}})
