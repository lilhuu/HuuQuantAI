import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.models.request import AutoTradingConfigRequest
from api.models.response import (
    CryptoKLineResponse,
    CryptoKLinesResponse,
    CryptoQuoteResponse,
    CryptoQuotesResponse,
    MacroOverviewResponse,
)
from api.services.crypto_service import CryptoService
from core.ai_paper_supervisor import AiPaperSupervisorRuntime
from core.auto_trading_engine import AutoTradingConfig


def _strategy_result():
    result = MagicMock()
    result.model_dump.return_value = {
        "signals": [{"symbol": "BTC/USDT"}],
        "winners": [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "price": 50_000,
                "confidence": 0.8,
                "strategy_id": "rsi",
                "reason": "strategy candidate",
            }
        ],
        "summary": [{"symbol": "BTC/USDT", "price": 50_000}],
    }
    return result


def _kline(end_time="2026-06-21T00:59:59Z"):
    return CryptoKLineResponse(
        symbol="BTC/USDT",
        period="1h",
        start_time="2026-06-21T00:00:00Z",
        end_time=end_time,
        open=49_500,
        high=50_200,
        low=49_300,
        close=50_000,
        volume=100,
        amount=5_000_000,
        count=1,
    )


def _ai_signal(action="BUY", confidence=0.8, notional=300):
    signal = MagicMock()
    signal.signal_id = "AI_SUPERVISED_1"
    signal.symbol = "BTC/USDT"
    signal.action = action
    signal.confidence = confidence
    signal.approval_status = "approved" if action != "HOLD" and confidence >= 0.65 else "blocked"
    signal.approval_reason = "approved" if signal.approval_status == "approved" else "HOLD or low confidence"
    signal.approved_notional_usdt = notional if signal.approval_status == "approved" else 0
    signal.response = {
        "symbol": "BTC/USDT",
        "action": action,
        "confidence": confidence,
        "suggested_notional_usdt": notional,
        "max_loss_usdt": 20,
        "time_horizon": "1h",
        "reason": "AI final decision",
        "risk_notes": ["paper only"],
        "invalid_if": ["new candle invalidates signal"],
        "model": "deepseek-v4-pro",
    }
    return MagicMock(signal=signal, context_summary={"quote": {"price": 50_000}})


def _service(tmp_path):
    service = CryptoService(
        {
            "crypto": {
                "exchange": "binance",
                "symbols": ["BTC/USDT"],
                "paper": {
                    "initial_cash": 10_000,
                    "max_order_notional": 2_000,
                    "max_position_ratio": 1,
                    "partial_fill_enabled": False,
                },
            },
            "risk": {
                "max_order_notional": 300,
                "allow_short_selling": False,
                "allow_leverage": False,
                "real_trading_enabled": False,
            },
            "auto_trading": {
                "enabled": False,
                "decision_mode": "ai_supervised",
                "symbols": ["BTC/USDT"],
                "period": "1h",
                "max_positions": 3,
                "max_order_notional": 300,
                "max_daily_loss": 200,
                "max_consecutive_losses": 3,
                "cooldown_minutes": 60,
                "ai_confidence_threshold": 0.65,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.04,
            },
            "ai": {
                "enabled": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "fallback_model": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "max_order_notional": 300,
                "min_confidence_for_order": 0.65,
            },
            "storage": {"db_path": str(tmp_path / "ai-supervisor.db")},
        }
    )
    service.run_strategies = AsyncMock(return_value=_strategy_result())
    service.get_klines = AsyncMock(
        return_value=CryptoKLinesResponse(symbol="BTC/USDT", period="1h", items=[_kline()], count=1)
    )
    service.get_quotes = AsyncMock(
        return_value=CryptoQuotesResponse(
            items=[CryptoQuoteResponse(symbol="BTC/USDT", price=50_000, source="unit")],
            count=1,
            source="unit",
        )
    )
    service.get_macro_overview = AsyncMock(return_value=MacroOverviewResponse(data={}, gate={"state": "ALLOW_FULL"}))
    service.analyze_ai_signal = AsyncMock(return_value=_ai_signal())
    service.testnet_executor.place_order = MagicMock(side_effect=AssertionError("testnet must not be called"))
    return service


def test_ai_supervised_config_is_safe_and_backward_compatible():
    legacy = AutoTradingConfig.from_dict({})
    assert legacy.decision_mode == "strategy"
    assert legacy.real_trading_enabled is False

    request = AutoTradingConfigRequest(decision_mode="ai_supervised")
    assert request.ai_model == "deepseek-v4-pro"
    assert request.ai_fallback_model == "deepseek-v4-flash"
    assert request.ai_confidence_threshold == 0.65
    assert request.stop_loss_pct == 0.02
    assert request.take_profit_pct == 0.04


def test_ai_supervisor_runtime_deduplicates_candles_and_blocks_after_three_failures():
    runtime = AiPaperSupervisorRuntime(max_provider_failures=3)
    assert runtime.should_evaluate("BTC/USDT", "2026-06-22T00:59:59Z") is True
    runtime.record_attempt("BTC/USDT", "2026-06-22T00:59:59Z")
    assert runtime.should_evaluate("BTC/USDT", "2026-06-22T00:59:59Z") is False
    runtime.record_signal("BTC/USDT", "2026-06-22T00:59:59Z", "SIG_1", "BUY")
    assert runtime.should_evaluate("BTC/USDT", "2026-06-22T00:59:59Z") is False
    assert runtime.should_evaluate("BTC/USDT", "2026-06-22T01:59:59Z") is True

    assert runtime.record_provider_failure("one") is False
    assert runtime.record_provider_failure("two") is False
    assert runtime.record_provider_failure("three") is True
    assert runtime.status()["blocked_reason"] == "three"


def test_ai_supervised_cycle_places_only_paper_order_with_protective_prices(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.start()
    service.paper_broker.place_order = MagicMock(wraps=service.paper_broker.place_order)

    status = asyncio.run(service.run_auto_trading_cycle())

    assert status.order_count == 1
    service.analyze_ai_signal.assert_awaited_once()
    analyze_request = service.analyze_ai_signal.await_args.args[0]
    assert analyze_request.model == "deepseek-v4-pro"
    order_call = service.paper_broker.place_order.call_args.kwargs
    assert order_call["strategy"].startswith("ai-supervised:")
    assert order_call["stop_loss_price"] == 49_000
    assert order_call["take_profit_price"] == 52_000
    service.testnet_executor.place_order.assert_not_called()
    assert status.ai_supervisor["last_action"] == "BUY"


def test_ai_supervised_cycle_does_not_repeat_same_candle(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.start()

    asyncio.run(service.run_auto_trading_cycle())
    asyncio.run(service.run_auto_trading_cycle())

    service.analyze_ai_signal.assert_awaited_once()
    assert service.auto_trading_engine.status()["order_count"] == 1


def test_ai_supervised_cycle_processes_protective_exit_between_candles(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.start()
    asyncio.run(service.run_auto_trading_cycle())
    assert service.paper_broker.get_positions()

    service.get_quotes = AsyncMock(
        return_value=CryptoQuotesResponse(
            items=[CryptoQuoteResponse(symbol="BTC/USDT", price=48_000, source="unit")],
            count=1,
            source="unit",
        )
    )
    asyncio.run(service.run_auto_trading_cycle())

    assert service.paper_broker.get_positions() == []
    assert any(order.strategy == "protective_stop_loss" for order in service.paper_broker.orders.values())


@pytest.mark.parametrize(
    ("control_method", "expected_state"),
    [("pause_auto_trading", "paused"), ("stop_auto_trading", "stopped")],
)
def test_protective_exit_loop_survives_auto_trading_pause_and_stop(tmp_path, control_method, expected_state):
    async def scenario():
        service = _service(tmp_path / expected_state)
        service._protective_interval_seconds = 0.01
        order = service.paper_broker.place_order(
            "BTC/USDT",
            "BUY",
            0.006,
            50_000,
            strategy="ai-supervised:test",
            stop_loss_price=49_000,
            take_profit_price=52_000,
        )
        assert order.status == "filled"
        service.get_quotes = AsyncMock(
            return_value=CryptoQuotesResponse(
                items=[CryptoQuoteResponse(symbol="BTC/USDT", price=48_000, source="unit")],
                count=1,
                source="unit",
            )
        )
        service.auto_trading_engine.start()

        status = await getattr(service, control_method)()

        assert status.state == expected_state
        assert service._auto_loop_task is None
        for _ in range(50):
            if not service.paper_broker.get_positions():
                break
            await asyncio.sleep(0.01)
        assert service.paper_broker.get_positions() == []
        assert any(order.strategy == "protective_stop_loss" for order in service.paper_broker.orders.values())

    asyncio.run(scenario())


def test_protective_exit_loop_restores_with_background_tasks(tmp_path):
    original = _service(tmp_path)
    order = original.paper_broker.place_order(
        "BTC/USDT",
        "BUY",
        0.006,
        50_000,
        strategy="ai-supervised:test",
        stop_loss_price=49_000,
        take_profit_price=52_000,
    )
    assert order.status == "filled"

    async def scenario():
        restarted = _service(tmp_path)
        restarted._protective_interval_seconds = 0.01
        restarted.get_quotes = AsyncMock(
            return_value=CryptoQuotesResponse(
                items=[CryptoQuoteResponse(symbol="BTC/USDT", price=48_000, source="unit")],
                count=1,
                source="unit",
            )
        )

        restarted.start_background_tasks()
        for _ in range(50):
            if not restarted.paper_broker.get_positions():
                break
            await asyncio.sleep(0.01)
        await restarted.shutdown_background_tasks()

        assert restarted.paper_broker.get_positions() == []
        assert restarted._protective_loop_task is None
        assert any(
            item.strategy == "protective_stop_loss"
            for item in restarted.paper_broker.orders.values()
        )

    asyncio.run(scenario())


def test_protective_exit_loop_waits_for_live_quotes(tmp_path):
    async def scenario():
        service = _service(tmp_path)
        service._protective_interval_seconds = 0.01
        order = service.paper_broker.place_order(
            "BTC/USDT",
            "BUY",
            0.006,
            50_000,
            strategy="ai-supervised:test",
            stop_loss_price=49_000,
            take_profit_price=52_000,
        )
        assert order.status == "filled"

        quote_calls = 0
        position_present_before_live = False

        async def get_quotes(*_args, **_kwargs):
            nonlocal quote_calls, position_present_before_live
            quote_calls += 1
            if quote_calls == 1:
                return CryptoQuotesResponse(
                    items=[CryptoQuoteResponse(symbol="BTC/USDT", price=48_000, source="cache")],
                    count=1,
                    source="cache_binance",
                )
            position_present_before_live = bool(service.paper_broker.get_positions())
            return CryptoQuotesResponse(
                items=[CryptoQuoteResponse(symbol="BTC/USDT", price=48_000, source="unit")],
                count=1,
                source="unit",
            )

        service.get_quotes = AsyncMock(side_effect=get_quotes)
        service.start_background_tasks()
        for _ in range(50):
            if not service.paper_broker.get_positions():
                break
            await asyncio.sleep(0.01)
        await service.shutdown_background_tasks()

        assert quote_calls >= 2
        assert position_present_before_live is True
        assert service.paper_broker.get_positions() == []

    asyncio.run(scenario())


def test_ai_supervised_hold_and_low_confidence_never_place_orders(tmp_path):
    for response in [_ai_signal("HOLD", 0.9, 0), _ai_signal("BUY", 0.4, 300)]:
        service = _service(tmp_path / response.signal.action / str(response.signal.confidence))
        service.analyze_ai_signal = AsyncMock(return_value=response)
        service.auto_trading_engine.start()
        service.paper_broker.place_order = MagicMock(wraps=service.paper_broker.place_order)

        status = asyncio.run(service.run_auto_trading_cycle())

        service.paper_broker.place_order.assert_not_called()
        assert status.order_count == 0


def test_ai_supervised_uses_its_own_confidence_threshold(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.config.ai_confidence_threshold = 0.9
    service.analyze_ai_signal = AsyncMock(return_value=_ai_signal("BUY", 0.8, 300))
    service.auto_trading_engine.start()
    service.paper_broker.place_order = MagicMock(wraps=service.paper_broker.place_order)

    status = asyncio.run(service.run_auto_trading_cycle())

    service.paper_broker.place_order.assert_not_called()
    assert status.last_decisions[0].status == "skipped"
    assert "confidence" in status.last_decisions[0].message


def test_ai_supervised_provider_failures_block_after_three_cycles(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.start()
    service.analyze_ai_signal = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    service.paper_broker.place_order = MagicMock(wraps=service.paper_broker.place_order)

    for index in range(3):
        service.get_klines = AsyncMock(
            return_value=CryptoKLinesResponse(
                symbol="BTC/USDT",
                period="1h",
                    items=[_kline(f"2026-06-21T0{index}:59:59Z")],
                count=1,
            )
        )
        asyncio.run(service.run_auto_trading_cycle())

    status = service.auto_trading_engine.status()
    assert status["state"] == "blocked"
    assert status["ai_supervisor"]["provider_failure_count"] == 3
    service.paper_broker.place_order.assert_not_called()


def test_ai_supervised_provider_failure_is_not_retried_on_same_candle(tmp_path):
    service = _service(tmp_path)
    service.auto_trading_engine.start()
    service.analyze_ai_signal = AsyncMock(side_effect=RuntimeError("provider unavailable"))

    asyncio.run(service.run_auto_trading_cycle())
    asyncio.run(service.run_auto_trading_cycle())

    service.analyze_ai_signal.assert_awaited_once()
    assert service.ai_supervisor.provider_failure_count == 1


def test_ai_supervised_start_requires_provider_key_and_restart_stays_stopped(monkeypatch, tmp_path):
    service = _service(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    blocked = asyncio.run(service.start_auto_trading())
    assert blocked.state == "blocked"
    assert "API key" in blocked.last_message

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    restarted = _service(tmp_path / "restart")
    restarted.auto_trading_engine.config.enabled = True
    status = asyncio.run(restarted.get_auto_trading_status())
    assert status.state == "stopped"
    assert status.enabled is False
    assert status.ai_supervisor["enabled"] is False
