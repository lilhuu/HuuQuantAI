from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.main import app
from api.services.crypto_service import CryptoService
from core.backtest_validation import HigherTimeframeTrend
from core.conflict_resolver import ConflictResolver
from core.crypto_market_data_provider import CryptoMarketDataProvider
from core.crypto_strategy_engine import StrategySignal


def _signal(
    symbol="BTC/USDT",
    action="BUY",
    confidence=0.8,
    timeframe="1h",
    strategy_id="s1",
    strategy_type="dual_ma",
    regime_score=0.0,
):
    direction = 1 if action == "BUY" else -1 if action == "SELL" else 0
    return StrategySignal(
        strategy_id=strategy_id,
        strategy_name=strategy_id,
        strategy_type=strategy_type,
        symbol=symbol,
        action=action,
        price=100.0,
        confidence=confidence,
        weight=1.0,
        weighted_score=confidence * direction,
        reason="unit",
        timestamp="2026-05-18T00:00:00",
        timeframe=timeframe,
        regime_score=regime_score,
    )


def test_no_conflict_single_signal_wins():
    result = ConflictResolver(max_positions=2).resolve([_signal()])

    assert len(result.winners) == 1
    assert result.winners[0].symbol == "BTC/USDT"
    assert result.blocked == []


def test_same_direction_different_timeframe_picks_best():
    result = ConflictResolver().resolve(
        [
            _signal(timeframe="1h", confidence=0.8, strategy_id="one_hour"),
            _signal(timeframe="4h", confidence=0.9, strategy_id="four_hour"),
        ]
    )

    assert result.winners[0].strategy_id == "four_hour"
    assert result.blocked[0].strategy_id == "one_hour"


def test_buy_sell_conflict_blocks_all():
    result = ConflictResolver().resolve(
        [
            _signal(action="BUY", timeframe="1h"),
            _signal(action="SELL", timeframe="4h", strategy_id="sell"),
        ]
    )

    assert result.winners == []
    assert len(result.blocked) == 2
    assert "timeframe_conflict" in result.block_reasons["BTC/USDT"]


def test_regime_score_boosts_ranking():
    result = ConflictResolver().resolve(
        [
            _signal(confidence=0.7, regime_score=1.0, strategy_id="regime_strong"),
            _signal(confidence=0.79, regime_score=0.0, strategy_id="confidence_strong"),
        ]
    )

    assert result.winners[0].strategy_id == "regime_strong"


def test_higher_tf_down_trend_blocks_mean_reversion_buy():
    result = ConflictResolver().resolve(
        [_signal(strategy_type="bollinger", action="BUY")],
        {"BTC/USDT": HigherTimeframeTrend(direction="down")},
    )

    assert result.winners == []
    assert result.blocked[0].reason.startswith("higher_tf_trend_block")


def test_higher_tf_up_trend_blocks_mean_reversion_sell():
    result = ConflictResolver().resolve(
        [_signal(strategy_type="rsi", action="SELL")],
        {"BTC/USDT": HigherTimeframeTrend(direction="up")},
    )

    assert result.winners == []
    assert result.blocked[0].reason.startswith("higher_tf_trend_block")


def test_trend_strategies_not_blocked_by_higher_tf():
    result = ConflictResolver().resolve(
        [_signal(strategy_type="dual_ma", action="BUY")],
        {"BTC/USDT": HigherTimeframeTrend(direction="down")},
    )

    assert len(result.winners) == 1


def test_neutral_trend_does_not_block_anything():
    result = ConflictResolver().resolve(
        [_signal(strategy_type="rsi", action="BUY")],
        {"BTC/USDT": HigherTimeframeTrend(direction="neutral")},
    )

    assert len(result.winners) == 1


def test_max_positions_limit():
    signals = [
        _signal(symbol="BTC/USDT", confidence=0.9, strategy_id="btc"),
        _signal(symbol="ETH/USDT", confidence=0.8, strategy_id="eth"),
        _signal(symbol="SOL/USDT", confidence=0.7, strategy_id="sol"),
        _signal(symbol="BNB/USDT", confidence=0.6, strategy_id="bnb"),
    ]
    result = ConflictResolver(max_positions=2).resolve(signals)

    assert [item.symbol for item in result.winners] == ["BTC/USDT", "ETH/USDT"]
    assert len(result.blocked) == 2
    assert all(item.reason == "max_positions_limit" for item in result.blocked)


def test_empty_and_hold_signals_return_empty():
    assert ConflictResolver().resolve([]).winners == []
    assert ConflictResolver().resolve([_signal(action="HOLD")]).winners == []


def test_missing_higher_tf_trends_no_blocking():
    result = ConflictResolver().resolve([_signal(strategy_type="bollinger", action="BUY")])

    assert len(result.winners) == 1


def test_score_formula():
    candidate = ConflictResolver().resolve([_signal(confidence=0.75, regime_score=-0.4)]).winners[0]

    assert candidate.score == 79.0


def test_multi_timeframe_strategy_api(monkeypatch, tmp_path):
    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
        normalized = "BTC/USDT" if "BTC" in symbol else "ETH/USDT"
        return [
            {
                "symbol": normalized,
                "period": timeframe,
                "start_time": f"2026-05-18T{index % 24:02d}:00:00Z",
                "end_time": f"2026-05-18T{index % 24:02d}:59:59Z",
                "open": 100 + index,
                "high": 101 + index,
                "low": 99 + index,
                "close": 100 + index,
                "volume": 100,
                "amount": (100 + index) * 100,
                "count": 1,
            }
            for index in range(max(80, min(limit, 120)))
        ]

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)
    service = CryptoService(
        {
            "crypto": {"exchange": "binance", "symbols": ["BTC/USDT", "ETH/USDT"]},
            "storage": {"db_path": str(tmp_path / "multi_tf_api.db")},
        }
    )
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/crypto/strategies/run",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "symbols": ["BTC/USDT"],
                    "period": "1h",
                    "timeframes": ["1h", "4h"],
                    "limit": 100,
                    "max_positions": 1,
                    "strategies": [
                        {
                            "strategy_id": "momentum_multi",
                            "type": "momentum",
                            "symbols": ["BTC/USDT"],
                            "parameters": {"lookback_period": 5, "buy_threshold": 0.01},
                        }
                    ],
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["signals"]
            assert payload["winners"]
            assert payload["signals"][0]["timeframe"] in {"1h", "4h"}
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
