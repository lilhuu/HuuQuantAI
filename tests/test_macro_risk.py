from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.main import app
from api.services.crypto_service import CryptoService
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.macro_data_provider import MacroDataProvider, MacroSnapshot
from core.macro_risk import MacroGateState, MacroRiskEvaluator


def _snapshot(**overrides):
    payload = {
        "timestamp": "2026-05-18T00:00:00Z",
        "dxy_available": False,
        "m2_available": False,
        "btc_dom_available": False,
        "gold_available": False,
        "spx_available": False,
        "yields_available": False,
    }
    payload.update(overrides)
    return MacroSnapshot(**payload)


def _candles_for_buy():
    closes = [100] * 30 + [102, 104, 106, 108, 112]
    return [
        {
            "symbol": "BTC/USDT",
            "period": "1h",
            "start_time": f"2026-05-18T{index % 24:02d}:00:00Z",
            "end_time": f"2026-05-18T{index % 24:02d}:59:59Z",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100,
            "amount": close * 100,
            "count": 1,
        }
        for index, close in enumerate(closes)
    ]


def test_macro_score_m2_expansion_positive():
    result = MacroRiskEvaluator().evaluate(_snapshot(m2_available=True, m2_change_3m_pct=10.0))

    assert result.score > 0
    assert result.state == MacroGateState.ALLOW_FULL


def test_macro_score_dxy_surge_negative():
    result = MacroRiskEvaluator().evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=5.0))

    assert result.score < -0.9
    assert result.state == MacroGateState.BLOCK_NEW_RISK


def test_macro_score_all_neutral():
    result = MacroRiskEvaluator().evaluate(
        _snapshot(
            dxy_available=True,
            dxy_change_30d_pct=0.0,
            m2_available=True,
            m2_change_3m_pct=0.0,
            btc_dom_available=True,
            btc_dom_change_30d_pct=0.0,
        )
    )

    assert result.score == 0.0
    assert result.state == MacroGateState.ALLOW_FULL


def test_macro_risk_thresholds_are_configurable():
    snapshot = _snapshot(dxy_available=True, dxy_change_30d_pct=1.0)

    default_result = MacroRiskEvaluator().evaluate(snapshot)
    strict_result = MacroRiskEvaluator({"block_threshold": -0.05, "reduce_threshold": 0.0}).evaluate(snapshot)

    assert default_result.state == MacroGateState.ALLOW_REDUCED
    assert strict_result.state == MacroGateState.BLOCK_NEW_RISK


def test_block_new_risk_when_dxy_up_and_m2_down():
    result = MacroRiskEvaluator().evaluate(
        _snapshot(
            dxy_available=True,
            dxy_change_30d_pct=1.5,
            m2_available=True,
            m2_change_3m_pct=-1.5,
        )
    )

    assert result.state == MacroGateState.BLOCK_NEW_RISK
    assert result.position_size_multiplier == 0.0
    assert result.max_concurrent_positions == 0


def test_allow_reduced_at_minus_15():
    result = MacroRiskEvaluator().evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=0.75))

    assert result.state == MacroGateState.ALLOW_REDUCED
    assert result.position_size_multiplier == 0.5
    assert result.confidence_penalty == 8.0
    assert result.entry_threshold_adjustment == 8.0


def test_yield_inversion_and_gold_surge_penalties():
    evaluator = MacroRiskEvaluator()
    neutral = evaluator.evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=0.0))
    stressed = evaluator.evaluate(
        _snapshot(
            dxy_available=True,
            dxy_change_30d_pct=0.0,
            yields_available=True,
            yield_spread_10y2y=-1.0,
            gold_available=True,
            gold_change_30d_pct=10.0,
        )
    )

    assert stressed.score < neutral.score
    assert "YIELD_INVERTED" in stressed.reason
    assert "GOLD_SURGE" in stressed.reason


def test_missing_sources_still_work():
    result = MacroRiskEvaluator().evaluate(_snapshot(btc_dom_available=True, btc_dom_change_30d_pct=-5.0))

    assert result.score > 0
    assert result.state == MacroGateState.ALLOW_FULL


def test_macro_gate_blocks_buy_and_reduces_signal():
    engine = CryptoStrategyEngine()
    config = engine.normalize_configs(
        [
            {
                "strategy_id": "macro_momentum",
                "type": "momentum",
                "symbols": ["BTC/USDT"],
                "parameters": {"lookback_period": 5, "buy_threshold": 0.01, "sell_threshold": -0.02},
            }
        ],
        ["BTC/USDT"],
    )[0]
    signal = engine.evaluate_strategy(config, "BTC/USDT", _candles_for_buy())
    assert signal is not None
    assert signal.action == "BUY"

    blocked = engine.apply_macro_gate(signal, MacroRiskEvaluator().evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=5.0)))
    assert blocked.action == "HOLD"
    assert "[Macro BLOCK]" in blocked.reason

    signal2 = engine.evaluate_strategy(config, "BTC/USDT", _candles_for_buy())
    original_confidence = signal2.confidence
    reduced = engine.apply_macro_gate(
        signal2,
        MacroRiskEvaluator().evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=0.75)),
    )
    assert reduced.action == "BUY"
    assert reduced.confidence < original_confidence
    assert "[Macro REDUCED]" in reduced.reason


def test_strategy_run_exposes_macro_blocked_signals():
    engine = CryptoStrategyEngine()
    config = engine.normalize_configs(
        [
            {
                "strategy_id": "macro_run_momentum",
                "type": "momentum",
                "symbols": ["BTC/USDT"],
                "parameters": {"lookback_period": 5, "buy_threshold": 0.01, "sell_threshold": -0.02},
            }
        ],
        ["BTC/USDT"],
    )

    result = engine.run(
        {"BTC/USDT": _candles_for_buy()},
        config,
        macro_gate=MacroRiskEvaluator().evaluate(_snapshot(dxy_available=True, dxy_change_30d_pct=5.0)),
    )

    assert result["signals"][0]["blocked"] is True
    assert result["signals"][0]["macro_gate_state"] == "BLOCK_NEW_RISK"
    assert result["blocked"][0]["strategy_id"] == "macro_run_momentum"


def test_bollinger_blocks_mean_reversion_buy_against_higher_timeframe_downtrend():
    engine = CryptoStrategyEngine()
    config = engine.normalize_configs(
        [
            {
                "strategy_id": "bollinger_guard",
                "type": "bollinger",
                "symbols": ["BTC/USDT"],
                "parameters": {"period": 20, "stddev_multiplier": 2.0},
            }
        ],
        ["BTC/USDT"],
    )[0]
    candles = [
        {"symbol": "BTC/USDT", "period": "1h", "close": close}
        for close in ([100] * 19 + [80])
    ]

    unguarded = engine.evaluate_strategy(config, "BTC/USDT", candles)
    guarded = engine.evaluate_strategy(
        engine._with_higher_tf_trend(
            config,
            {"direction": "down", "four_hour_change_pct": -4.0, "daily_change_pct": -8.0},
        ),
        "BTC/USDT",
        candles,
    )

    assert unguarded.action == "BUY"
    assert guarded.action == "HOLD"
    assert "higher timeframe" in guarded.reason
    assert guarded.confidence <= 0.15


def test_macro_provider_cache_returns_cached_value():
    provider = MacroDataProvider()
    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return {"dxy_available": True, "dxy_price": 100 + calls["count"]}

    first = provider._cached("unit", 300, loader)
    second = provider._cached("unit", 300, loader)

    assert first == second
    assert calls["count"] == 1


def test_macro_api_endpoint(tmp_path):
    service = CryptoService(
        {
            "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
            "storage": {"db_path": str(tmp_path / "macro_api.db")},
        }
    )
    service.macro_provider.fetch_snapshot = lambda: _snapshot(
        dxy_available=True,
        dxy_change_30d_pct=0.75,
        m2_available=True,
        m2_change_3m_pct=0.0,
    )

    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/crypto/macro", headers={"Authorization": "Bearer test-token"})
            assert response.status_code == 200
            payload = response.json()
            assert payload["gate"]["state"] in {"ALLOW_REDUCED", "ALLOW_FULL", "BLOCK_NEW_RISK"}
            assert payload["data"]["dxy_available"] is True
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
