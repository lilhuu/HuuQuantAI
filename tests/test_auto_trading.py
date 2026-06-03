import asyncio

from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.main import app
from api.services.crypto_service import CryptoService
from core.auto_trading_engine import AutoTradingEngine
from core.crypto_market_data_provider import CryptoMarketDataProvider


class _FakeStrategyResult:
    def model_dump(self):
        return {"signals": [], "winners": [], "summary": []}


def test_auto_trading_blocks_real_switch_and_builds_buy_decision():
    blocked_engine = AutoTradingEngine({"symbols": ["BTC/USDT"], "real_trading_enabled": True})
    status = blocked_engine.start()
    assert status["state"] == "blocked"
    assert status["real_trading_enabled"] is False

    engine = AutoTradingEngine(
        {
            "symbols": ["BTC/USDT"],
            "per_trade_position_ratio": 0.1,
            "max_order_notional": 1000,
            "confidence_threshold": 0.2,
        }
    )
    engine.start()
    decisions = engine.build_order_decisions(
        {
            "signals": [{"symbol": "BTC/USDT"}],
            "winners": [{"symbol": "BTC/USDT", "action": "BUY", "price": 50000, "confidence": 0.8, "strategy_id": "rsi"}],
            "summary": [{"symbol": "BTC/USDT", "price": 50000}],
        },
        {"equity": 10000, "cash": 10000, "available_cash": 10000},
        [],
        place_orders=True,
    )

    assert decisions[0]["status"] == "ready"
    assert decisions[0]["quantity"] == 0.02
    assert decisions[0]["notional"] == 1000
    assert [step["name"] for step in decisions[0]["steps"]][-1] == "submit"
    assert all(step["status"] == "pass" for step in decisions[0]["steps"])


def test_auto_trading_skips_duplicate_buy_and_short_sell():
    engine = AutoTradingEngine({"symbols": ["BTC/USDT"], "confidence_threshold": 0.1})
    engine.start()
    positions = [{"symbol": "BTC/USDT", "quantity": 0.01, "available": 0.01}]

    buy_decision = engine.build_order_decisions(
        {"summary": [{"symbol": "BTC/USDT", "action": "BUY", "price": 50000, "confidence": 0.8}]},
        {"equity": 10000, "cash": 10000, "available_cash": 10000},
        positions,
    )[0]
    assert buy_decision["status"] == "skipped"
    assert "already exists" in buy_decision["message"]

    sell_decision = engine.build_order_decisions(
        {"summary": [{"symbol": "ETH/USDT", "action": "SELL", "price": 3000, "confidence": 0.8}]},
        {"equity": 10000, "cash": 10000, "available_cash": 10000},
        positions,
    )[0]
    assert sell_decision["status"] == "skipped"
    assert "short selling disabled" in sell_decision["message"]


def test_auto_trading_daily_loss_triggers_kill_switch_and_cooldown():
    engine = AutoTradingEngine(
        {
            "symbols": ["BTC/USDT"],
            "max_daily_loss": 100,
            "cooldown_minutes": 15,
            "confidence_threshold": 0.1,
        }
    )
    engine.start()
    engine.build_order_decisions({"summary": []}, {"equity": 10_000, "cash": 10_000}, [])

    decisions = engine.build_order_decisions(
        {"summary": [{"symbol": "BTC/USDT", "action": "BUY", "price": 50_000, "confidence": 0.9}]},
        {"equity": 9_850, "cash": 9_850, "available_cash": 9_850},
        [],
    )

    status = engine.status()
    assert status["state"] == "paused"
    assert status["risk_state"]["kill_switch_active"] is True
    assert status["risk_state"]["daily_pnl"] == -150
    assert decisions[0]["status"] == "skipped"
    assert decisions[0]["steps"][-1]["name"] == "risk_cooldown"
    assert decisions[0]["steps"][-1]["status"] == "fail"


def test_auto_trading_consecutive_losses_trigger_kill_switch():
    engine = AutoTradingEngine({"max_consecutive_losses": 2, "cooldown_minutes": 10})
    engine.start()

    engine.record_order_result({}, {"status": "filled", "realized_pnl": -1})
    assert engine.status()["risk_state"]["consecutive_losses"] == 1
    assert engine.status()["risk_state"]["kill_switch_active"] is False

    engine.record_order_result({}, {"status": "filled", "realized_pnl": -2})
    status = engine.status()
    assert status["state"] == "paused"
    assert status["risk_state"]["consecutive_losses"] == 2
    assert status["risk_state"]["kill_switch_active"] is True
    assert "consecutive losses" in status["risk_state"]["reason"]


def test_auto_trading_api_status_config_and_scan(monkeypatch, tmp_path):
    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
        return [
            {
                "symbol": "BTC/USDT",
                "period": timeframe,
                "start_time": f"2026-05-12T{i:02d}:00:00Z",
                "end_time": f"2026-05-12T{i:02d}:59:59Z",
                "open": 100 + i,
                "high": 102 + i,
                "low": 99 + i,
                "close": 101 + i,
                "volume": 10 + i,
                "amount": (101 + i) * (10 + i),
                "count": 1,
            }
            for i in range(max(30, min(limit, 80)))
        ]

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: CryptoService(
        {
            "crypto": {
                "exchange": "binance",
                "symbols": ["BTC/USDT"],
                "paper": {
                    "initial_cash": 10000,
                    "max_order_notional": 5000,
                    "max_position_ratio": 1.0,
                    "partial_fill_enabled": False,
                },
            },
            "auto_trading": {"symbols": ["BTC/USDT"], "confidence_threshold": 0.1},
            "storage": {"db_path": str(tmp_path / "auto_trading.db")},
        }
    )

    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-token"}
            status = client.get("/api/v1/crypto/auto/status", headers=headers)
            assert status.status_code == 200
            assert status.json()["mode"] == "paper"

            config = client.put(
                "/api/v1/crypto/auto/config",
                headers=headers,
                json={
                    "symbols": ["BTC/USDT"],
                    "period": "1h",
                    "max_positions": 2,
                    "max_order_notional": 500,
                    "real_trading_enabled": True,
                    "strategies": [{"strategy_id": "auto_momo", "type": "momentum", "symbols": ["BTC/USDT"], "weight": 1}],
                },
            )
            assert config.status_code == 200
            assert config.json()["config"]["real_trading_enabled"] is False

            scan = client.post("/api/v1/crypto/auto/scan", headers=headers)
            assert scan.status_code == 200
            assert scan.json()["cycle_count"] >= 1

            started = client.post("/api/v1/crypto/auto/start", headers=headers)
            assert started.status_code == 200
            assert started.json()["state"] == "running"

            stopped = client.post("/api/v1/crypto/auto/stop", headers=headers)
            assert stopped.status_code == 200
            assert stopped.json()["state"] == "stopped"
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()


def test_auto_trading_background_loop_start_and_pause(tmp_path):
    async def scenario():
        service = CryptoService(
            {
                "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
                "auto_trading": {"symbols": ["BTC/USDT"], "scan_interval_seconds": 5},
                "storage": {"db_path": str(tmp_path / "loop.db")},
            }
        )

        async def fake_run_strategies(_request):
            return _FakeStrategyResult()

        service.run_strategies = fake_run_strategies
        started = await service.start_auto_trading()
        assert started.state == "running"
        assert started.loop_running is True
        assert started.next_run_at

        await asyncio.sleep(0.02)
        assert service.auto_trading_engine.status()["cycle_count"] >= 1

        paused = await service.pause_auto_trading()
        assert paused.state == "paused"
        assert paused.loop_running is False
        assert paused.next_run_at == ""

    asyncio.run(scenario())


def test_auto_trading_background_loop_survives_unhandled_scan_error(tmp_path):
    async def scenario():
        service = CryptoService(
            {
                "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
                "auto_trading": {"symbols": ["BTC/USDT"], "scan_interval_seconds": 5},
                "storage": {"db_path": str(tmp_path / "loop_guard.db")},
            }
        )

        async def broken_scan():
            raise RuntimeError("scan exploded")

        service._run_auto_trading_cycle_locked = broken_scan
        started = await service.start_auto_trading()
        assert started.state == "running"

        await asyncio.sleep(0.02)
        task = service._auto_loop_task
        assert task is not None
        assert task.done() is False
        status = service.auto_trading_engine.status()
        assert status["loop_running"] is True
        assert status["last_error_type"] == "RuntimeError"
        assert any(log["event"] == "cycle_failed" and log["payload"].get("source") == "auto_loop" for log in status["logs"])

        paused = await service.pause_auto_trading()
        assert paused.state == "paused"
        assert paused.loop_running is False

    asyncio.run(scenario())


def test_auto_trading_scan_lock_skips_overlapping_cycle(tmp_path):
    async def scenario():
        service = CryptoService(
            {
                "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
                "auto_trading": {"symbols": ["BTC/USDT"]},
                "storage": {"db_path": str(tmp_path / "lock.db")},
            }
        )

        async with service._auto_scan_lock:
            status = await service.run_auto_trading_cycle()

        assert status.cycle_count == 0
        assert any(log.event == "scan_skipped_locked" for log in status.logs)

    asyncio.run(scenario())
