from fastapi.testclient import TestClient

import api.main as main_module


class FakeBroker:
    def __init__(self, storage_path):
        self.storage_path = str(storage_path)
        self.is_connected = True

    def get_account_info(self):
        return {"real_trading_enabled": False}


class FakeProvider:
    exchange_id = "binance"

    def fetch_quotes(self, symbols):
        return [{"symbol": symbols[0], "price": 100.0, "source": "binance"}]


class BrokenProvider(FakeProvider):
    def fetch_quotes(self, symbols):
        raise RuntimeError("network down")


class FakeCache:
    def __init__(self, rows=None):
        self._rows = rows or []

    def get_quotes(self, symbols):
        return self._rows


class FakeService:
    def __init__(self, storage_path, provider=None, cache=None):
        self.default_symbols = ["BTC/USDT"]
        self.paper_broker = FakeBroker(storage_path)
        self.provider = provider or FakeProvider()
        self.market_cache = cache or FakeCache()


def test_healthz_reports_live_dependencies(monkeypatch, tmp_path):
    service = FakeService(tmp_path / "trading.db")
    monkeypatch.setattr(main_module, "get_crypto_service", lambda: service)

    response = TestClient(main_module.app).get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["sqlite"]["ok"] is True
    assert payload["checks"]["market_data"]["source"] == "binance"


def test_healthz_degrades_when_live_market_uses_cache(monkeypatch, tmp_path):
    service = FakeService(
        tmp_path / "trading.db",
        provider=BrokenProvider(),
        cache=FakeCache([{"symbol": "BTC/USDT", "price": 100.0}]),
    )
    monkeypatch.setattr(main_module, "get_crypto_service", lambda: service)

    response = TestClient(main_module.app).get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["data_feed_connected"] is False
    assert payload["checks"]["market_data"]["cache_available"] is True
