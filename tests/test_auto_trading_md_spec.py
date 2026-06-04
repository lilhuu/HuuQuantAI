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
BUY_STEPS = [
    "real_trading_gate",
    "risk_cooldown",
    "kill_switch",
    "market_data",
    "confidence",
    "submit_mode",
    "duplicate_position",
    "max_positions",
    "notional",
    "quantity",
]


def _pipeline(config=None, risk_state=None, cooldown=False):
    return DecisionPipeline(config or AutoTradingConfig(), risk_state or RiskState(), cooldown)


def _args(**overrides):
    payload = {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "price": 50000.0,
        "confidence": 0.5,
        "strategy_id": "unit_strategy",
        "reason": "unit",
        "candidate": {},
        "equity": 10000.0,
        "cash": 10000.0,
        "positions": {},
        "current_position_count": 0,
        "place_orders": True,
    }
    payload.update(overrides)
    return payload


def _step(decision, name):
    for item in decision["steps"]:
        if item["name"] == name:
            return item
    raise AssertionError(f"missing step {name}")


def _candidate(symbol="BTC/USDT", action="BUY", price=50000.0, confidence=0.8, strategy_id="unit"):
    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "confidence": confidence,
        "strategy_id": strategy_id,
        "reason": "unit",
    }


def _test(name, check):
    def wrapper():
        check()

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__doc__ = f"md spec: {name}"
    return wrapper


def _assert_config(payload, field, expected):
    assert getattr(AutoTradingConfig.from_dict(payload), field) == expected


def _config_defaults():
    config = AutoTradingConfig.from_dict({})
    assert config.enabled is False
    assert config.mode == "paper"
    assert config.symbols == DEFAULT_SYMBOLS
    assert config.scan_interval_seconds == 30
    assert config.max_positions == 3


def _config_strategies_default():
    config = AutoTradingConfig.from_dict({})
    assert [item["strategy_id"] for item in config.strategies] == ["auto_rsi", "auto_macd", "auto_momentum"]


def _config_roundtrip():
    config = AutoTradingConfig.from_dict({"symbols": ["btc/usdt"], "scan_interval_seconds": 60, "max_positions": 5})
    assert AutoTradingConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


def _real_trading_false_roundtrip():
    config = AutoTradingConfig.from_dict({"real_trading_enabled": True})
    assert config.real_trading_enabled is False
    assert config.to_dict()["real_trading_enabled"] is False


def _initial_state():
    status = AutoTradingEngine().status()
    assert status["state"] == "stopped"
    assert status["enabled"] is False
    assert status["cycle_count"] == 0
    assert status["order_count"] == 0
    assert status["signal_count"] == 0


def _start_running():
    status = AutoTradingEngine().start()
    assert status["state"] == "running"
    assert status["enabled"] is True


def _pause_running():
    engine = AutoTradingEngine()
    engine.start()
    status = engine.pause()
    assert status["state"] == "paused"
    assert status["enabled"] is False
    assert status["loop_running"] is False


def _stop_running():
    engine = AutoTradingEngine()
    engine.start()
    status = engine.stop()
    assert status["state"] == "stopped"
    assert status["enabled"] is False


def _resume_paused():
    engine = AutoTradingEngine()
    engine.start()
    engine.pause()
    assert engine.start()["state"] == "running"


def _start_blocked_real():
    engine = AutoTradingEngine()
    engine.config.real_trading_enabled = True
    status = engine.start()
    assert status["state"] == "blocked"
    assert any("real trading is blocked" in item["message"] for item in status["logs"])


def _start_blocked_cooldown():
    engine = AutoTradingEngine()
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    status = engine.start()
    assert status["state"] == "paused"
    assert "cooling down" in status["last_message"]


def _start_clears_kill_switch():
    engine = AutoTradingEngine()
    engine.risk_state.kill_switch_active = True
    engine.risk_state.reason = "manual stop"
    engine.start()
    assert engine.risk_state.kill_switch_active is False
    assert engine.risk_state.reason == ""


def _status_fields():
    assert set(AutoTradingEngine().status()) >= STATUS_FIELDS


def _decision(config=None, risk_state=None, cooldown=False, **overrides):
    return _pipeline(config, risk_state, cooldown).build_one(**_args(**overrides))


def _assert_skipped(decision, message, step_name, step_status="fail"):
    assert decision["status"] == "skipped"
    assert message in decision["message"]
    assert _step(decision, step_name)["status"] == step_status


def _gate_real_trading_blocked():
    _assert_skipped(_decision(AutoTradingConfig(real_trading_enabled=True)), "real trading is blocked", "real_trading_gate")


def _gate_real_trading_pass():
    assert _step(_decision(), "real_trading_gate")["status"] == "pass"


def _gate_cooldown_active():
    risk_state = RiskState(cooldown_until="2099-01-01T00:00:00")
    _assert_skipped(_decision(risk_state=risk_state, cooldown=True), "risk cooldown active", "risk_cooldown")


def _gate_kill_switch_active():
    risk_state = RiskState(kill_switch_active=True, reason="manual stop")
    _assert_skipped(_decision(risk_state=risk_state), "manual stop", "kill_switch")


def _gate_price_zero():
    _assert_skipped(_decision(price=0), "missing executable price", "market_data")


def _gate_price_negative():
    _assert_skipped(_decision(price=-100), "missing executable price", "market_data")


def _gate_confidence_below():
    _assert_skipped(
        _decision(AutoTradingConfig(confidence_threshold=0.35), confidence=0.1),
        "confidence below threshold 0.35",
        "confidence",
    )


def _gate_confidence_exact():
    decision = _decision(AutoTradingConfig(confidence_threshold=0.35), confidence=0.35)
    assert _step(decision, "confidence")["status"] == "pass"


def _gate_preview_mode():
    decision = _decision(place_orders=False)
    assert decision["status"] == "simulated"
    assert "decision preview only" in decision["message"]


def _buy_duplicate_blocked():
    _assert_skipped(_decision(positions={"BTC/USDT": {"quantity": 1.0}}), "position already exists", "duplicate_position")


def _buy_duplicate_pass():
    assert _step(_decision(positions={"BTC/USDT": {"quantity": 0.0}}), "duplicate_position")["status"] == "pass"


def _buy_max_positions_reached():
    _assert_skipped(
        _decision(AutoTradingConfig(max_positions=3), current_position_count=3),
        "max open positions reached",
        "max_positions",
    )


def _buy_max_positions_under_limit():
    decision = _decision(AutoTradingConfig(max_positions=3), current_position_count=2)
    assert _step(decision, "max_positions")["status"] == "pass"


def _buy_notional_below_min():
    decision = _decision(AutoTradingConfig(min_order_notional=999), equity=100, cash=100, price=100)
    _assert_skipped(decision, "notional below minimum", "notional")


def _buy_notional_exceeds_cash():
    decision = _decision(AutoTradingConfig(per_trade_position_ratio=0.1), equity=10000, cash=500, price=50000)
    assert decision["notional"] <= 500
    assert decision["status"] == "ready"


def _buy_notional_capped_by_max_order():
    decision = _decision(
        AutoTradingConfig(max_order_notional=1000, per_trade_position_ratio=1.0),
        equity=100000,
        cash=100000,
        price=100,
    )
    assert decision["notional"] == 1000


def _buy_quantity_rounded_zero():
    decision = _decision(AutoTradingConfig(min_order_notional=0), equity=1, cash=1, price=1_000_000_000)
    _assert_skipped(decision, "quantity rounded to zero", "quantity")


def _buy_success_basic():
    decision = _decision(AutoTradingConfig(per_trade_position_ratio=0.1, max_order_notional=2000))
    assert decision["status"] == "ready"
    assert decision["quantity"] == 0.02
    assert decision["notional"] == pytest.approx(1000)


def _buy_success_all_steps():
    decision = _decision(AutoTradingConfig(per_trade_position_ratio=0.1, max_order_notional=2000))
    assert [_step(decision, step)["status"] for step in BUY_STEPS] == ["pass"] * len(BUY_STEPS)


def _sell_no_position():
    _assert_skipped(_decision(action="SELL", positions={}), "no position to sell; short selling disabled", "short_selling")


def _sell_with_position():
    decision = _decision(action="SELL", positions={"BTC/USDT": {"quantity": 1.5}}, price=50000)
    assert decision["status"] == "ready"
    assert decision["quantity"] == 1.5
    assert decision["notional"] == 75000.0


def _sell_quantity_matches_held():
    decision = _decision(action="SELL", positions={"BTC/USDT": {"quantity": 0.12345678}}, price=50000)
    assert decision["quantity"] == 0.12345678


def _risk_daily_reset():
    engine = AutoTradingEngine()
    engine.risk_state.trading_day = "2025-01-01"
    engine.risk_state.day_start_equity = 5000
    engine._update_risk_state({"equity": 10000})
    assert engine.risk_state.trading_day == datetime.now(timezone.utc).date().isoformat()
    assert engine.risk_state.day_start_equity == 10000
    assert engine.risk_state.daily_pnl == 0


def _risk_daily_pnl():
    engine = AutoTradingEngine()
    engine.risk_state.trading_day = datetime.now(timezone.utc).date().isoformat()
    engine.risk_state.day_start_equity = 10000
    engine._update_risk_state({"equity": 9500})
    assert engine.risk_state.daily_pnl == -500


def _kill_switch_daily_loss():
    engine = AutoTradingEngine({"max_daily_loss": 200})
    engine.risk_state.trading_day = datetime.now(timezone.utc).date().isoformat()
    engine.risk_state.day_start_equity = 10000
    engine._update_risk_state({"equity": 9700})
    assert engine.risk_state.kill_switch_active is True
    assert engine.state == "paused"


def _no_kill_switch_below_daily_loss():
    engine = AutoTradingEngine({"max_daily_loss": 500})
    engine.risk_state.trading_day = datetime.now(timezone.utc).date().isoformat()
    engine.risk_state.day_start_equity = 10000
    engine._update_risk_state({"equity": 9600})
    assert engine.risk_state.kill_switch_active is False


def _record_loss(engine, pnl=-100, status="filled"):
    engine.record_order_result({}, {"status": status, "realized_pnl": pnl, "message": "unit"})


def _consecutive_losses_tracking():
    engine = AutoTradingEngine()
    for _ in range(3):
        _record_loss(engine)
    assert engine.risk_state.consecutive_losses == 3


def _consecutive_losses_reset_on_win():
    engine = AutoTradingEngine()
    for _ in range(3):
        _record_loss(engine)
    _record_loss(engine, pnl=50)
    assert engine.risk_state.consecutive_losses == 0


def _consecutive_losses_not_counted_pending():
    engine = AutoTradingEngine()
    _record_loss(engine, status="pending")
    assert engine.order_count == 0
    assert engine.risk_state.consecutive_losses == 0


def _kill_switch_consecutive_losses():
    engine = AutoTradingEngine({"max_consecutive_losses": 3})
    for _ in range(3):
        _record_loss(engine)
    assert engine.risk_state.kill_switch_active is True
    assert "consecutive losses" in engine.risk_state.reason


def _cooldown_expires():
    engine = AutoTradingEngine()
    engine.risk_state.kill_switch_active = True
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert engine._cooldown_active() is False
    assert engine.risk_state.kill_switch_active is False


def _cooldown_still_active():
    engine = AutoTradingEngine()
    engine.risk_state.cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert engine._cooldown_active() is True


def _cooldown_invalid_iso():
    engine = AutoTradingEngine()
    engine.risk_state.cooldown_until = "not-a-date"
    assert engine._cooldown_active() is False


def _build_decisions(strategy_result, account=None, positions=None, config=None, place_orders=True):
    engine = AutoTradingEngine(config or {"confidence_threshold": 0.1, "max_positions": 20})
    decisions = engine.build_order_decisions(
        strategy_result,
        account or {"equity": 10000, "cash": 10000},
        positions or [],
        place_orders=place_orders,
    )
    return engine, decisions


def _empty_signals():
    _, decisions = _build_decisions({"signals": [], "summary": [], "winners": []})
    assert decisions == []


def _no_candidates():
    _, decisions = _build_decisions({"signals": [{"symbol": "BTC/USDT"}], "summary": [{"action": "HOLD"}], "winners": []})
    assert decisions == []


def _single_buy_signal():
    _, decisions = _build_decisions({"signals": [_candidate()], "summary": [_candidate()], "winners": []})
    assert len(decisions) == 1
    assert decisions[0]["symbol"] == "BTC/USDT"
    assert decisions[0]["action"] == "BUY"
    assert decisions[0]["quantity"] > 0


def _duplicate_symbol_action_deduped():
    _, decisions = _build_decisions({"summary": [_candidate(), _candidate()]})
    assert len(decisions) == 1


def _winners_priority():
    _, decisions = _build_decisions({"summary": [_candidate("BTC/USDT")], "winners": [_candidate("ETH/USDT")]})
    assert decisions[0]["symbol"] == "ETH/USDT"


def _cash_deducted_after_buy_ready():
    _, decisions = _build_decisions(
        {"summary": [_candidate("BTC/USDT", price=100), _candidate("ETH/USDT", price=100)]},
        {"equity": 10000, "cash": 1500},
        [],
        {"symbols": ["BTC/USDT", "ETH/USDT"], "confidence_threshold": 0.1},
    )
    assert decisions[0]["notional"] == 1000
    assert decisions[1]["notional"] == 500


def _decisions_capped_at_50():
    engine, _ = _build_decisions({"summary": [_candidate(f"C{i}/USDT", price=100) for i in range(100)]}, {"equity": 100000, "cash": 100000})
    assert len(engine.last_decisions) <= 50


def _record_order_result_updates_counts():
    engine = AutoTradingEngine()
    for _ in range(3):
        _record_loss(engine, pnl=0)
    assert engine.order_count == 3


def _record_order_result_partial_fill_counts():
    engine = AutoTradingEngine()
    _record_loss(engine, status="partial_filled")
    assert engine.order_count == 1
    assert engine.risk_state.consecutive_losses == 1


def _logs_capped_at_500():
    engine = AutoTradingEngine()
    for index in range(600):
        engine._log("INFO", f"event_{index}", "message")
    assert len(engine.logs) <= 500


def _cycle_count_increments():
    engine = AutoTradingEngine()
    for _ in range(3):
        engine.build_order_decisions({"summary": []}, {"equity": 10000, "cash": 10000}, [])
    assert engine.cycle_count == 3


def _signal_count_accumulates():
    engine = AutoTradingEngine()
    engine.build_order_decisions({"signals": [{}, {}], "summary": []}, {"equity": 10000, "cash": 10000}, [])
    engine.build_order_decisions({"signals": [{}], "summary": []}, {"equity": 10000, "cash": 10000}, [])
    assert engine.signal_count == 3


def _mark_loop_updates_state():
    engine = AutoTradingEngine()
    engine.mark_loop(running=True, next_run_at="2099-01-01T00:00:00Z")
    assert engine.loop_running is True
    assert engine.next_run_at == "2099-01-01T00:00:00Z"


def _mark_loop_clears_next():
    engine = AutoTradingEngine()
    engine.mark_loop(running=True, next_run_at="2099-01-01T00:00:00Z")
    engine.mark_loop(running=False)
    assert engine.loop_running is False
    assert engine.next_run_at == ""


def _update_config_merge_partial():
    engine = AutoTradingEngine()
    before = list(engine.config.symbols)
    engine.update_config({"scan_interval_seconds": 60})
    assert engine.config.scan_interval_seconds == 60
    assert engine.config.symbols == before


def _update_config_blocks_real():
    engine = AutoTradingEngine()
    engine.update_config({"real_trading_enabled": True})
    assert engine.config.real_trading_enabled is False


def _update_config_logs_event():
    engine = AutoTradingEngine()
    engine.update_config({"scan_interval_seconds": 60})
    assert any(item["event"] == "config_updated" for item in engine.logs)


CONFIG_CASES = {
    "test_config_defaults": _config_defaults,
    "test_config_symbols_normalized": lambda: _assert_config({"symbols": ["btc/usdt", "eth/usdt"]}, "symbols", ["BTC/USDT", "ETH/USDT"]),
    "test_config_symbols_empty_fallback": lambda: _assert_config({"symbols": []}, "symbols", DEFAULT_SYMBOLS),
    "test_config_scan_interval_clamped_min": lambda: _assert_config({"scan_interval_seconds": 0}, "scan_interval_seconds", 5),
    "test_config_scan_interval_clamped_max": lambda: _assert_config({"scan_interval_seconds": 9999}, "scan_interval_seconds", 3600),
    "test_config_max_positions_clamped_min": lambda: _assert_config({"max_positions": 0}, "max_positions", 1),
    "test_config_max_positions_clamped_max": lambda: _assert_config({"max_positions": 999}, "max_positions", 20),
    "test_config_confidence_clamped_min": lambda: _assert_config({"confidence_threshold": -0.5}, "confidence_threshold", 0.0),
    "test_config_confidence_clamped_max": lambda: _assert_config({"confidence_threshold": 2.0}, "confidence_threshold", 1.0),
    "test_config_cooldown_clamped_min": lambda: _assert_config({"cooldown_minutes": 0}, "cooldown_minutes", 1),
    "test_config_cooldown_clamped_max": lambda: _assert_config({"cooldown_minutes": 99999}, "cooldown_minutes", 1440),
    "test_config_strategies_default": _config_strategies_default,
    "test_config_to_dict_roundtrip": _config_roundtrip,
    "test_config_mode_always_paper": lambda: _assert_config({"mode": "live"}, "mode", "paper"),
    "test_config_real_trading_always_false": _real_trading_false_roundtrip,
    "test_config_per_trade_ratio_clamped_min": lambda: _assert_config({"per_trade_position_ratio": 0}, "per_trade_position_ratio", 0.001),
    "test_config_per_trade_ratio_clamped_max": lambda: _assert_config({"per_trade_position_ratio": 2.0}, "per_trade_position_ratio", 1.0),
}

LIFECYCLE_CASES = {
    "test_initial_state_stopped": _initial_state,
    "test_start_transitions_to_running": _start_running,
    "test_pause_from_running": _pause_running,
    "test_stop_from_running": _stop_running,
    "test_resume_from_paused": _resume_paused,
    "test_start_blocked_when_real_trading": _start_blocked_real,
    "test_start_blocked_by_cooldown": _start_blocked_cooldown,
    "test_start_clears_kill_switch": _start_clears_kill_switch,
    "test_status_returns_all_fields": _status_fields,
}

PIPELINE_CASES = {
    "test_gate_real_trading_blocked": _gate_real_trading_blocked,
    "test_gate_real_trading_pass": _gate_real_trading_pass,
    "test_gate_cooldown_active": _gate_cooldown_active,
    "test_gate_kill_switch_active": _gate_kill_switch_active,
    "test_gate_price_zero": _gate_price_zero,
    "test_gate_price_negative": _gate_price_negative,
    "test_gate_confidence_below_threshold": _gate_confidence_below,
    "test_gate_confidence_exactly_at_threshold": _gate_confidence_exact,
    "test_gate_preview_mode": _gate_preview_mode,
    "test_buy_duplicate_position_blocked": _buy_duplicate_blocked,
    "test_buy_duplicate_position_pass": _buy_duplicate_pass,
    "test_buy_max_positions_reached": _buy_max_positions_reached,
    "test_buy_max_positions_under_limit": _buy_max_positions_under_limit,
    "test_buy_notional_below_min": _buy_notional_below_min,
    "test_buy_notional_exceeds_cash": _buy_notional_exceeds_cash,
    "test_buy_notional_capped_by_max_order": _buy_notional_capped_by_max_order,
    "test_buy_quantity_rounded_to_zero": _buy_quantity_rounded_zero,
    "test_buy_success_basic": _buy_success_basic,
    "test_buy_success_all_steps_present": _buy_success_all_steps,
    "test_sell_no_position_blocked": _sell_no_position,
    "test_sell_with_position_success": _sell_with_position,
    "test_sell_quantity_matches_held": _sell_quantity_matches_held,
}

RISK_CASES = {
    "test_risk_state_daily_reset": _risk_daily_reset,
    "test_risk_state_daily_pnl_calculation": _risk_daily_pnl,
    "test_kill_switch_on_daily_loss": _kill_switch_daily_loss,
    "test_no_kill_switch_below_daily_loss_limit": _no_kill_switch_below_daily_loss,
    "test_consecutive_losses_tracking": _consecutive_losses_tracking,
    "test_consecutive_losses_reset_on_win": _consecutive_losses_reset_on_win,
    "test_consecutive_losses_not_counted_on_pending": _consecutive_losses_not_counted_pending,
    "test_kill_switch_on_consecutive_losses": _kill_switch_consecutive_losses,
    "test_cooldown_expires": _cooldown_expires,
    "test_cooldown_still_active": _cooldown_still_active,
    "test_cooldown_invalid_iso_format": _cooldown_invalid_iso,
}

INTEGRATION_CASES = {
    "test_empty_signals": _empty_signals,
    "test_no_candidates": _no_candidates,
    "test_single_buy_signal": _single_buy_signal,
    "test_duplicate_symbol_action_deduped": _duplicate_symbol_action_deduped,
    "test_winners_priority_over_summary": _winners_priority,
    "test_cash_deducted_after_buy_ready": _cash_deducted_after_buy_ready,
    "test_decisions_capped_at_50": _decisions_capped_at_50,
    "test_record_order_result_updates_counts": _record_order_result_updates_counts,
    "test_record_order_result_partial_fill_counts": _record_order_result_partial_fill_counts,
    "test_logs_capped_at_500": _logs_capped_at_500,
    "test_cycle_count_increments": _cycle_count_increments,
    "test_signal_count_accumulates": _signal_count_accumulates,
    "test_mark_loop_updates_state": _mark_loop_updates_state,
    "test_mark_loop_clears_next_run": _mark_loop_clears_next,
    "test_update_config_merge_partial": _update_config_merge_partial,
    "test_update_config_blocks_real_trading": _update_config_blocks_real,
    "test_update_config_logs_event": _update_config_logs_event,
}

for _name, _check in {
    **CONFIG_CASES,
    **LIFECYCLE_CASES,
    **PIPELINE_CASES,
    **RISK_CASES,
    **INTEGRATION_CASES,
}.items():
    globals()[_name] = _test(_name, _check)
