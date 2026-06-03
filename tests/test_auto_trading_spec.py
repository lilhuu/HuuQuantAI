from datetime import datetime, timedelta, timezone

import pytest

from core.auto_trading_engine import AutoTradingConfig, AutoTradingEngine, DecisionPipeline, RiskState


DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
STATUS_FIELDS = {
    "state",
    "enabled",
    "mode",
    "config",
    "last_run_at",
    "last_message",
    "cycle_count",
    "signal_count",
    "order_count",
    "last_decisions",
    "logs",
    "risk_state",
    "real_trading_enabled",
    "loop_running",
    "next_run_at",
    "last_error_type",
}


def _make_pipeline(config=None, risk_state=None, cooldown=False):
    return DecisionPipeline(config or AutoTradingConfig(), risk_state or RiskState(), cooldown)


def _base_args(**overrides):
    payload = {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "price": 50000.0,
        "confidence": 0.5,
        "strategy_id": "test_strategy",
        "reason": "test",
        "candidate": {},
        "equity": 10000.0,
        "cash": 10000.0,
        "positions": {},
        "current_position_count": 0,
        "place_orders": True,
    }
    payload.update(overrides)
    return payload


def _step_status(decision, name):
    for step in decision["steps"]:
        if step["name"] == name:
            return step["status"]
    return ""


def _summary_candidate(symbol="BTC/USDT", action="BUY", price=50000, confidence=0.8, strategy_id="unit"):
    return {"symbol": symbol, "action": action, "price": price, "confidence": confidence, "strategy_id": strategy_id}


def test_config_defaults_and_roundtrip():
    config = AutoTradingConfig.from_dict(None)

    assert config.enabled is False
    assert config.mode == "paper"
    assert config.symbols == DEFAULT_SYMBOLS
    assert config.scan_interval_seconds == 30
    assert config.max_positions == 3
    assert [item["strategy_id"] for item in config.strategies] == ["auto_rsi", "auto_macd", "auto_momentum"]
    assert AutoTradingConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


@pytest.mark.parametrize(
    ("payload", "field", "expected"),
    [
        ({"symbols": ["btc/usdt", "eth/usdt"]}, "symbols", ["BTC/USDT", "ETH/USDT"]),
        ({"symbols": []}, "symbols", DEFAULT_SYMBOLS),
        ({"scan_interval_seconds": 0}, "scan_interval_seconds", 5),
        ({"scan_interval_seconds": 9999}, "scan_interval_seconds", 3600),
        ({"max_positions": 0}, "max_positions", 1),
        ({"max_positions": 999}, "max_positions", 20),
        ({"confidence_threshold": -0.5}, "confidence_threshold", 0.0),
        ({"confidence_threshold": 2.0}, "confidence_threshold", 1.0),
        ({"cooldown_minutes": 0}, "cooldown_minutes", 1),
        ({"cooldown_minutes": 99999}, "cooldown_minutes", 1440),
        ({"mode": "live"}, "mode", "paper"),
        ({"real_trading_enabled": True}, "real_trading_enabled", False),
        ({"per_trade_position_ratio": 0}, "per_trade_position_ratio", 0.001),
        ({"per_trade_position_ratio": 2.0}, "per_trade_position_ratio", 1.0),
    ],
)
def test_config_from_dict_clamps_and_normalizes(payload, field, expected):
    assert getattr(AutoTradingConfig.from_dict(payload), field) == expected


def test_engine_lifecycle_and_status_fields():
    engine = AutoTradingEngine()
    assert engine.status()["state"] == "stopped"
    assert engine.status()["enabled"] is False
    assert engine.status()["cycle_count"] == 0
    assert engine.status()["order_count"] == 0
    assert engine.status()["signal_count"] == 0
    assert set(engine.status()) >= STATUS_FIELDS

    assert engine.start()["state"] == "running"
    assert engine.status()["enabled"] is True
    assert engine.pause()["state"] == "paused"
    assert engine.status()["loop_running"] is False
    assert engine.start()["state"] == "running"
    assert engine.stop()["state"] == "stopped"


def test_engine_start_blocks_runtime_real_trading_and_cooldown_and_clears_kill_switch():
    engine = AutoTradingEngine()
    engine.config.real_trading_enabled = True
    assert engine.start()["state"] == "blocked"
    assert "real trading is blocked" in engine.last_message

    engine = AutoTradingEngine()
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert engine.start()["state"] == "paused"
    assert "cooling down" in engine.last_message

    engine = AutoTradingEngine()
    engine.risk_state.kill_switch_active = True
    engine.risk_state.reason = "manual"
    engine.start()
    assert engine.risk_state.kill_switch_active is False
    assert engine.risk_state.reason == ""


@pytest.mark.parametrize(
    ("config", "risk_state", "cooldown", "overrides", "message", "failed_step"),
    [
        (AutoTradingConfig(real_trading_enabled=True), None, False, {}, "real trading is blocked", "real_trading_gate"),
        (None, RiskState(cooldown_until="2099-01-01T00:00:00"), True, {}, "risk cooldown active", "risk_cooldown"),
        (None, RiskState(kill_switch_active=True, reason="manual stop"), False, {}, "manual stop", "kill_switch"),
        (None, None, False, {"price": 0}, "missing executable price", "market_data"),
        (None, None, False, {"price": -100}, "missing executable price", "market_data"),
        (AutoTradingConfig(confidence_threshold=0.35), None, False, {"confidence": 0.1}, "confidence below threshold 0.35", "confidence"),
    ],
)
def test_decision_pipeline_common_blocks(config, risk_state, cooldown, overrides, message, failed_step):
    decision = _make_pipeline(config=config, risk_state=risk_state, cooldown=cooldown).build_one(**_base_args(**overrides))

    assert decision["status"] == "skipped"
    assert message in decision["message"]
    assert _step_status(decision, failed_step) == "fail"


def test_decision_pipeline_common_passes_and_preview_mode():
    decision = _make_pipeline(AutoTradingConfig(confidence_threshold=0.35)).build_one(**_base_args(confidence=0.35))
    assert _step_status(decision, "real_trading_gate") == "pass"
    assert _step_status(decision, "confidence") == "pass"

    preview = _make_pipeline().build_one(**_base_args(place_orders=False))
    assert preview["status"] == "simulated"
    assert "decision preview only" in preview["message"]


@pytest.mark.parametrize(
    ("overrides", "message", "step"),
    [
        ({"positions": {"BTC/USDT": {"quantity": 1.0}}}, "position already exists", "duplicate_position"),
        ({"current_position_count": 3}, "max open positions reached", "max_positions"),
        ({"equity": 100, "cash": 100, "price": 100}, "notional below minimum", "notional"),
    ],
)
def test_decision_pipeline_buy_blocks(overrides, message, step):
    config = AutoTradingConfig(min_order_notional=999) if step == "notional" else AutoTradingConfig(max_positions=3)
    decision = _make_pipeline(config).build_one(**_base_args(**overrides))

    assert decision["status"] == "skipped"
    assert message in decision["message"]
    assert _step_status(decision, step) == "fail"


def test_decision_pipeline_buy_sizing_caps_and_success_steps():
    cash_capped = _make_pipeline(AutoTradingConfig(per_trade_position_ratio=0.1)).build_one(**_base_args(cash=500))
    assert cash_capped["notional"] == 500

    max_capped = _make_pipeline(AutoTradingConfig(per_trade_position_ratio=1.0, max_order_notional=1000)).build_one(
        **_base_args(price=100, equity=100000, cash=100000)
    )
    assert max_capped["notional"] == 1000

    rounded_zero = _make_pipeline(AutoTradingConfig(min_order_notional=0)).build_one(**_base_args(equity=1, cash=1, price=1_000_000_000))
    assert rounded_zero["status"] == "skipped"
    assert "quantity rounded to zero" in rounded_zero["message"]

    success = _make_pipeline(AutoTradingConfig(per_trade_position_ratio=0.1, max_order_notional=2000)).build_one(**_base_args())
    assert success["status"] == "ready"
    assert success["quantity"] == 0.02
    assert success["notional"] == 1000
    for step in ["real_trading_gate", "risk_cooldown", "kill_switch", "market_data", "confidence", "submit_mode", "duplicate_position", "max_positions", "notional", "quantity"]:
        assert _step_status(success, step) == "pass"


def test_decision_pipeline_sell_blocks_and_succeeds():
    blocked = _make_pipeline().build_one(**_base_args(action="SELL", positions={}))
    assert blocked["status"] == "skipped"
    assert blocked["message"] == "no position to sell; short selling disabled"

    success = _make_pipeline().build_one(
        **_base_args(action="SELL", positions={"BTC/USDT": {"quantity": 1.5}}, price=50000)
    )
    assert success["status"] == "ready"
    assert success["quantity"] == 1.5
    assert success["notional"] == 75000.0

    exact = _make_pipeline().build_one(
        **_base_args(action="SELL", positions={"BTC/USDT": {"quantity": 0.12345678}}, price=50000)
    )
    assert exact["quantity"] == 0.12345678


def test_risk_state_daily_pnl_kill_switch_and_cooldown():
    engine = AutoTradingEngine({"max_daily_loss": 200})
    engine.risk_state.trading_day = "2025-01-01"
    engine.risk_state.day_start_equity = 5000
    engine._update_risk_state({"equity": 10000})
    assert engine.risk_state.day_start_equity == 10000
    assert engine.risk_state.daily_pnl == 0

    engine._update_risk_state({"equity": 9700})
    assert engine.risk_state.daily_pnl == -300
    assert engine.risk_state.kill_switch_active is True
    assert engine.state == "paused"

    engine = AutoTradingEngine({"max_daily_loss": 500})
    engine.risk_state.trading_day = datetime.now(timezone.utc).date().isoformat()
    engine.risk_state.day_start_equity = 10000
    engine._update_risk_state({"equity": 9600})
    assert engine.risk_state.kill_switch_active is False

    engine.risk_state.kill_switch_active = True
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert engine._cooldown_active() is False
    assert engine.risk_state.kill_switch_active is False
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    assert engine._cooldown_active() is True
    engine.risk_state.cooldown_until = "not-a-date"
    assert engine._cooldown_active() is False


def test_record_order_result_counts_losses_wins_and_pending():
    engine = AutoTradingEngine({"max_consecutive_losses": 3})
    engine.record_order_result({}, {"status": "pending", "realized_pnl": -100})
    assert engine.order_count == 0
    assert engine.risk_state.consecutive_losses == 0

    for _ in range(3):
        engine.record_order_result({}, {"status": "filled", "realized_pnl": -100})
    assert engine.order_count == 3
    assert engine.risk_state.consecutive_losses == 3
    assert engine.risk_state.kill_switch_active is True

    engine.record_order_result({}, {"status": "partial_filled", "realized_pnl": 50})
    assert engine.order_count == 4
    assert engine.risk_state.consecutive_losses == 0


def test_build_order_decisions_candidates_counts_and_last_decisions():
    engine = AutoTradingEngine({"symbols": ["BTC/USDT", "ETH/USDT"], "confidence_threshold": 0.1, "max_positions": 20})
    empty = engine.build_order_decisions({"signals": [], "summary": [], "winners": []}, {"equity": 10000, "cash": 10000}, [])
    assert empty == []
    no_candidate = engine.build_order_decisions({"signals": [{}], "summary": [{"action": "HOLD"}]}, {"equity": 10000, "cash": 10000}, [])
    assert no_candidate == []

    decisions = engine.build_order_decisions(
        {
            "signals": [{}, {}],
            "summary": [_summary_candidate(), _summary_candidate()],
            "winners": [],
        },
        {"equity": 10000, "cash": 10000},
        [],
    )
    assert len(decisions) == 1
    assert decisions[0]["symbol"] == "BTC/USDT"
    assert engine.signal_count == 3

    winner = engine.build_order_decisions(
        {"summary": [_summary_candidate(symbol="BTC/USDT")], "winners": [_summary_candidate(symbol="ETH/USDT")]},
        {"equity": 10000, "cash": 10000},
        [],
    )
    assert winner[0]["symbol"] == "ETH/USDT"

    cash_engine = AutoTradingEngine({"symbols": ["BTC/USDT", "ETH/USDT"], "confidence_threshold": 0.1})
    two = cash_engine.build_order_decisions(
        {"summary": [_summary_candidate("BTC/USDT", price=100), _summary_candidate("ETH/USDT", price=100)]},
        {"equity": 10000, "cash": 1500},
        [],
    )
    assert two[0]["notional"] == 1000
    assert two[1]["notional"] == 500

    many_engine = AutoTradingEngine({"confidence_threshold": 0.1, "max_positions": 20})
    many_engine.build_order_decisions(
        {"summary": [_summary_candidate(f"COIN{i}/USDT", price=100) for i in range(100)]},
        {"equity": 100000, "cash": 100000},
        [],
    )
    assert len(many_engine.last_decisions) == 50
    assert many_engine.cycle_count == 1


def test_logs_mark_loop_and_update_config():
    engine = AutoTradingEngine()
    for index in range(600):
        engine._log("INFO", f"event_{index}", "message")
    assert len(engine.logs) == 500

    engine.mark_loop(running=True, next_run_at="2099-01-01T00:00:00Z")
    assert engine.loop_running is True
    assert engine.next_run_at
    engine.mark_loop(running=False)
    assert engine.loop_running is False
    assert engine.next_run_at == ""

    old_symbols = list(engine.config.symbols)
    status = engine.update_config({"scan_interval_seconds": 60, "real_trading_enabled": True})
    assert status["config"]["scan_interval_seconds"] == 60
    assert status["config"]["symbols"] == old_symbols
    assert status["config"]["real_trading_enabled"] is False
    assert any(log["event"] == "config_updated" for log in engine.logs)
