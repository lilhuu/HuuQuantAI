from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.main import app
from api.services.crypto_service import CryptoService
from core.crypto_market_data_provider import CryptoMarketDataProvider
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.regime_detector import MarketRegime, RegimeDetector


def _series_candles(closes: list[float], symbol: str = "BTC/USDT") -> list[dict]:
    return [
        {
            "symbol": symbol,
            "period": "1h",
            "start_time": f"2026-05-01T{index % 24:02d}:00:00Z",
            "end_time": f"2026-05-01T{index % 24:02d}:59:59Z",
            "open": close,
            "high": close + 1,
            "low": max(close - 1, 0.01),
            "close": close,
            "volume": 100 + index,
            "amount": close * (100 + index),
            "count": 1,
        }
        for index, close in enumerate(closes)
    ]


def test_trend_up_detection():
    closes = [100 + index * 2 for index in range(80)]
    result = RegimeDetector().detect(closes=closes, highs=[v + 1 for v in closes], lows=[v - 1 for v in closes])

    assert result.regime == MarketRegime.TREND_UP
    assert result.score > 0.35
    assert result.features.trend_strength > 0


def test_trend_down_detection():
    closes = [300 - index * 2 for index in range(80)]
    result = RegimeDetector().detect(closes=closes, highs=[v + 1 for v in closes], lows=[v - 1 for v in closes])

    assert result.regime == MarketRegime.TREND_DOWN
    assert result.score < -0.35
    assert result.features.momentum < 0


def test_range_detection():
    closes = [100 + ((index % 4) - 1.5) * 0.3 for index in range(80)]
    result = RegimeDetector().detect(closes=closes, highs=[v + 1 for v in closes], lows=[v - 1 for v in closes])

    assert result.regime == MarketRegime.RANGE
    assert abs(result.score) <= 0.35


def test_risk_off_on_volatility_spike():
    closes = [100 + index * 0.5 for index in range(80)]
    highs = [value * 1.25 for value in closes]
    lows = [value * 0.75 for value in closes]
    result = RegimeDetector().detect(closes=closes, highs=highs, lows=lows)

    assert result.regime == MarketRegime.RISK_OFF
    assert result.features.volatility_spike > 0.85


def test_funding_overheat_penalty_and_confidence():
    closes = [100 + index * 2 for index in range(80)]
    detector = RegimeDetector()
    normal = detector.detect(closes=closes)
    overheated = detector.detect(
        closes=closes,
        funding_rate=0.0015,
    )

    assert overheated.features.funding_overheat == 1.0
    assert overheated.score < normal.score
    assert overheated.confidence > normal.confidence


def test_missing_and_empty_data_graceful():
    empty = RegimeDetector().detect(closes=[])
    short = RegimeDetector().detect(closes=[1, 2, 3, 4])

    assert empty.regime == MarketRegime.UNKNOWN
    assert empty.confidence == 0.0
    assert short.regime == MarketRegime.UNKNOWN
    assert short.features.trend_strength == 0.0


def test_orderbook_imbalance_and_volume_anomaly():
    detector = RegimeDetector()

    assert detector._calc_orderbook_imbalance(200, 100) > 0
    assert detector._calc_orderbook_imbalance(100, 200) < 0
    assert detector._calc_volume_anomaly([100] * 20 + [350]) > 0.5


def test_regime_filter_blocks_mean_reversion_in_trend():
    engine = CryptoStrategyEngine()
    config = engine.normalize_configs(
        [
            {
                "strategy_id": "bollinger_regime",
                "type": "bollinger",
                "symbols": ["BTC/USDT"],
                "parameters": {"period": 20, "stddev_multiplier": 1.0},
            }
        ],
        ["BTC/USDT"],
    )[0]
    candles = _series_candles([100] * 40 + [115])
    signal = engine.evaluate_strategy_with_regime(config, "BTC/USDT", candles, MarketRegime.TREND_UP, 0.6)

    assert signal is not None
    assert signal.action == "HOLD"
    assert "regime(TREND_UP)_blocked" in signal.reason


def test_regime_filter_allows_trend_strategy_in_trend():
    engine = CryptoStrategyEngine()
    config = engine.normalize_configs(
        [
            {
                "strategy_id": "momentum_regime",
                "type": "momentum",
                "symbols": ["BTC/USDT"],
                "parameters": {"lookback_period": 5, "buy_threshold": 0.01, "sell_threshold": -0.01},
            }
        ],
        ["BTC/USDT"],
    )[0]
    candles = _series_candles([120 - index for index in range(40)])
    signal = engine.evaluate_strategy_with_regime(config, "BTC/USDT", candles, MarketRegime.TREND_DOWN, -0.6)

    assert signal is not None
    assert signal.action == "SELL"
    assert "blocked" not in signal.reason


def test_regime_api_endpoint(monkeypatch, tmp_path):
    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
        return _series_candles([100 + index * 2 for index in range(min(limit, 120))], symbol)

    def fake_funding(self, symbol):
        return {"symbol": symbol, "funding_rate": 0.0002, "timestamp": "2026-05-18T00:00:00Z"}

    def fake_orderbook(self, symbol, limit=20):
        return {
            "symbol": symbol,
            "bids": [[100, 2.0], [99, 1.0]],
            "asks": [[101, 1.0], [102, 1.0]],
            "timestamp": "2026-05-18T00:00:00Z",
            "source": "test",
        }

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_funding_rate", fake_funding)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_order_book", fake_orderbook)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: CryptoService(
        {
            "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
            "storage": {"db_path": str(tmp_path / "regime_api.db")},
        }
    )

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/crypto/market/regime?symbols=BTC/USDT&period=1h&limit=100",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == 1
            assert payload["items"][0]["symbol"] == "BTC/USDT"
            assert payload["items"][0]["regime"] in {"TREND_UP", "RANGE", "RISK_OFF"}
            assert "features" in payload["items"][0]
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
