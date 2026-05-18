import pytest

from core.crypto_market_data_provider import CryptoMarketDataProvider
from core.exchange_resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    MaxRetriesExceededError,
    RetryConfig,
    retry_call,
)


def _retry_config():
    return RetryConfig(max_retries=2, base_delay_seconds=0, jitter=False, retryable_exceptions=(ConnectionError,))


def test_retry_succeeds_on_second_attempt():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionError("temporary")
        return "ok"

    assert retry_call(flaky, config=_retry_config()) == "ok"
    assert calls["count"] == 2


def test_retry_exhausts_and_fallback():
    def fail():
        raise ConnectionError("down")

    with pytest.raises(MaxRetriesExceededError):
        retry_call(fail, config=_retry_config())
    assert retry_call(fail, config=_retry_config(), fallback=lambda: "cache") == "cache"


def test_non_retryable_exception_not_retried():
    calls = {"count": 0}

    def fail():
        calls["count"] += 1
        raise ValueError("bad symbol")

    with pytest.raises(ValueError):
        retry_call(fail, config=_retry_config())
    assert calls["count"] == 1


def test_circuit_breaker_opens_and_recovers(monkeypatch):
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=1))

    def fail():
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            breaker.call(fail)
    assert breaker.state.value == "open"
    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(lambda: "ok")

    monkeypatch.setattr("time.time", lambda: breaker.opened_at + 2)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state.value == "closed"


def test_provider_connection_health_report():
    provider = CryptoMarketDataProvider({"exchange": "binance"})
    health = provider.get_connection_health()

    assert set(health) == {"quotes", "ohlcv", "orderbook"}
    assert health["quotes"]["state"] == "closed"
