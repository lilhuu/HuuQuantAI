from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.main import app
from api.services.crypto_service import CryptoService
from core.crypto_market_data_provider import CryptoMarketDataProvider
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.walk_forward_backtest import (
    WalkForwardConfig,
    WalkForwardRunner,
    build_strict_factor_audit,
    create_walk_forward_windows,
)


def _candles(count: int = 180, symbol: str = "BTC/USDT") -> list[dict]:
    rows = []
    for i in range(count):
        cycle = (i % 24) - 12
        trend = i * 0.35
        close = 100 + trend + cycle * 0.8
        rows.append(
            {
                "symbol": symbol,
                "period": "1h",
                "start_time": f"2026-05-{1 + (i // 24):02d}T{i % 24:02d}:00:00Z",
                "end_time": f"2026-05-{1 + (i // 24):02d}T{i % 24:02d}:59:59Z",
                "open": close - 0.4,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 10 + i,
                "amount": close * (10 + i),
                "count": 1,
            }
        )
    return rows


def test_create_walk_forward_windows_and_factor_audit():
    config = WalkForwardConfig(train_ratio=0.6, validation_ratio=0.2, min_train_candles=30, step_size=20)
    windows = create_walk_forward_windows(_candles(160), config)
    audit = build_strict_factor_audit()

    assert windows
    assert windows[0]["round_index"] == 0
    assert len(windows[0]["train_klines"]) >= 30
    assert len(windows[0]["validation_klines"]) >= 30
    assert audit["price"]["available"] is True
    assert audit["macro"]["available"] is False
    assert audit["funding_rate"]["available"] is False

    live_audit = build_strict_factor_audit(has_macro=True, has_funding_rate=True, has_orderbook=True)
    assert live_audit["macro"]["available"] is True
    assert live_audit["funding_rate"]["available"] is True
    assert live_audit["orderbook"]["available"] is True


def test_walk_forward_runner_selects_params_and_summarizes():
    engine = CryptoStrategyEngine()
    configs = engine.normalize_configs(
        [
            {
                "strategy_id": "momentum_wf",
                "type": "momentum",
                "symbols": ["BTC/USDT"],
                "parameters": {"position_ratio": 0.25},
            }
        ],
        ["BTC/USDT"],
    )
    runner = WalkForwardRunner(
        WalkForwardConfig(
            train_ratio=0.6,
            validation_ratio=0.2,
            min_train_candles=30,
            step_size=30,
            perturbation_runs=5,
            initial_cash=5000,
            fee_rate=0.001,
            slippage_rate=0.0005,
            period="1h",
        )
    )
    result = runner.run(
        {"BTC/USDT": _candles(180)},
        configs,
        param_grids={"momentum": [{"lookback_period": 5, "buy_threshold": 0.01, "sell_threshold": -0.02}]},
    )

    assert result["rounds"]
    assert result["rounds"][0]["strategy_id"] == "momentum_wf"
    assert result["rounds"][0]["params"]["lookback_period"] == 5
    assert result["rounds"][0]["train_start"]
    assert result["rounds"][0]["validation_start"]
    assert result["by_strategy"][0]["round_count"] == len(result["rounds"])
    assert result["by_symbol"][0]["symbol"] == "BTC/USDT"
    assert result["config"]["initial_cash"] == 5000


def test_walk_forward_api_endpoint(monkeypatch, tmp_path):
    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
        return _candles(min(limit, 180), "BTC/USDT")

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: CryptoService(
        {
            "crypto": {
                "exchange": "binance",
                "symbols": ["BTC/USDT"],
                "paper": {"initial_cash": 10000, "max_position_ratio": 1.0},
            },
            "storage": {"db_path": str(tmp_path / "wf_api.db")},
        }
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/crypto/strategies/walk-forward",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "symbols": ["BTC/USDT"],
                    "period": "1h",
                    "limit": 180,
                    "train_ratio": 0.6,
                    "validation_ratio": 0.2,
                    "min_train_candles": 30,
                    "step_size": 30,
                    "perturbation_runs": 3,
                    "strategies": [
                        {
                            "strategy_id": "api_momentum",
                            "type": "momentum",
                            "symbols": ["BTC/USDT"],
                            "parameters": {"position_ratio": 0.25},
                        }
                    ],
                    "param_grid": {
                        "momentum": [
                            {"lookback_period": 5, "buy_threshold": 0.01, "sell_threshold": -0.02}
                        ]
                    },
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["rounds"]
            assert payload["factor_audit"]["price"]["available"] is True
            assert payload["by_strategy"][0]["strategy_id"] == "api_momentum"
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
