from fastapi.testclient import TestClient

import api.dependencies as dependencies
from api.dependencies import get_auth_service, get_current_user, get_crypto_service
from api.main import app
from api.routers import crypto_ws
from api.services.auth_service import AuthService
from api.services.crypto_service import CryptoService
from core.binance_market_stream import build_binance_stream_url, normalize_binance_stream_message
from core.binance_testnet_executor import BinanceTestnetExecutor
from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_market_data_provider import CryptoMarketDataProvider
from core.crypto_paper_broker import CryptoPaperBrokerExecutor
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.parameter_optimizer import CryptoStrategyParameterOptimizer


def test_crypto_paper_broker_buy_sell_and_rejects():
    broker = CryptoPaperBrokerExecutor(
        {
            "initial_cash": 10000,
            "max_order_notional": 5000,
            "max_position_ratio": 1.0,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
            "partial_fill_enabled": False,
        }
    )

    buy = broker.place_order("BTC/USDT", "BUY", 0.001, 1000)
    assert buy.status == "filled"
    assert broker.cash < 10000
    assert broker.get_positions()[0]["quantity"] == 0.001

    oversell = broker.place_order("BTC/USDT", "SELL", 0.01, 1000)
    assert oversell.status == "rejected"
    assert "short selling is disabled" in oversell.message

    too_large = broker.place_order("ETH/USDT", "BUY", 10, 1000)
    assert too_large.status == "rejected"
    assert "single order notional" in too_large.message


def test_crypto_paper_broker_partial_fill_cancel_and_real_switch_refusal():
    broker = CryptoPaperBrokerExecutor(
        {
            "initial_cash": 10000,
            "max_order_notional": 10000,
            "max_position_ratio": 1.0,
            "partial_fill_enabled": True,
            "partial_fill_min_notional": 3000,
            "partial_fill_ratio": 0.5,
        }
    )

    order = broker.place_order("ETHUSDT", "BUY", 4, 1000)
    assert order.status == "partial_filled"
    assert order.filled_quantity == 2
    assert broker.cancel_order(order.order_id) is True
    assert broker.orders[order.order_id].status == "cancelled"
    assert any(item["event"] == "order_cancelled" for item in broker.get_paper_logs(20))

    live_blocked = CryptoPaperBrokerExecutor({"real_trading_enabled": True}).place_order("BTC/USDT", "BUY", 0.001, 1000)
    assert live_blocked.status == "rejected"
    assert "real_trading_enabled=true" in live_blocked.message


def test_crypto_paper_broker_persists_and_restores(tmp_path):
    storage_path = tmp_path / "paper_state.db"
    config = {
        "storage_path": str(storage_path),
        "initial_cash": 10000,
        "max_order_notional": 5000,
        "max_position_ratio": 1.0,
        "fee_rate": 0.001,
        "slippage_rate": 0.0005,
        "partial_fill_enabled": False,
    }

    broker = CryptoPaperBrokerExecutor(config)
    order = broker.place_order("BTC/USDT", "BUY", 0.002, 1000)
    assert order.status == "filled"
    assert storage_path.exists()

    restored = CryptoPaperBrokerExecutor(config)
    account = restored.get_account_info()
    positions = restored.get_positions()
    orders = restored.get_orders(limit=10)
    logs = restored.get_paper_logs(20)

    assert account["cash"] == broker.cash
    assert positions[0]["symbol"] == "BTC/USDT"
    assert positions[0]["quantity"] == 0.002
    assert orders["total"] >= 1
    assert orders["items"][0]["order_id"] == order.order_id
    assert restored.get_equity_curve(10)
    assert any(item["event"] == "account_restored" for item in logs)


def test_binance_testnet_executor_credentials_gate_and_dry_run(tmp_path):
    executor = BinanceTestnetExecutor(
        {
            "enabled": False,
            "real_trading_enabled": True,
            "dry_run": True,
            "required_confirmation": "I_UNDERSTAND_CRYPTO_TESTNET",
            "credential_store_path": str(tmp_path / "testnet_credentials.enc"),
            "credential_key_path": str(tmp_path / "testnet.key"),
        }
    )

    status = executor.status()
    assert status["has_api_key"] is False
    assert status["real_trading_enabled"] is False
    assert status["configured_real_trading_enabled"] is True

    blocked = executor.place_order(symbol="BTC/USDT", action="BUY", quantity=0.001, price=1000, dry_run=False)
    assert blocked.status == "rejected"
    assert "confirmation phrase" in blocked.message or "real_trading_enabled=true" in blocked.message

    saved = executor.save_credentials("test-key-123456", "test-secret-abcdef")
    assert saved["success"] is True
    assert saved["has_api_key"] is True
    assert (tmp_path / "testnet_credentials.enc").exists()
    assert b"test-secret-abcdef" not in (tmp_path / "testnet_credentials.enc").read_bytes()

    wrong = executor.enable_testnet_orders("WRONG")
    assert wrong["success"] is False

    enabled = executor.enable_testnet_orders("I_UNDERSTAND_CRYPTO_TESTNET")
    assert enabled["success"] is True

    dry_run = executor.place_order(symbol="BTCUSDT", action="BUY", quantity=0.001, price=1000, dry_run=True)
    assert dry_run.status == "dry_run"
    assert dry_run.symbol == "BTC/USDT"
    assert "no Binance Testnet order was sent" in dry_run.message

    live_blocked = executor.place_order(symbol="BTC/USDT", action="BUY", quantity=0.001, price=1000, dry_run=False)
    assert live_blocked.status == "rejected"
    assert "transport is intentionally disabled" in live_blocked.message

    mainnet_blocked = BinanceTestnetExecutor({"mainnet_real_trading_enabled": True})
    assert mainnet_blocked.place_order(symbol="BTC/USDT", action="BUY", quantity=0.001, price=1000).status == "rejected"


def test_crypto_api_and_removed_legacy_routes(monkeypatch, tmp_path):
    def fake_quotes(self, symbols):
      return [
          {
              "symbol": "BTC/USDT",
              "price": 65000.0,
              "open": 64000.0,
              "high": 66000.0,
              "low": 63000.0,
              "volume": 10.0,
              "amount": 650000.0,
              "change": 0.015625,
              "change_amount": 1000.0,
              "bid": 64999.0,
              "ask": 65001.0,
              "timestamp": "2026-05-12T00:00:00Z",
              "source": "binance",
          }
      ]

    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
      normalized = "BTC/USDT" if "BTC" in symbol else "ETH/USDT"
      return [
          {
              "symbol": normalized,
              "period": timeframe,
              "start_time": f"2026-05-12T{i:02d}:00:00Z",
              "end_time": f"2026-05-12T{i:02d}:59:59Z",
              "open": 64000.0 + i,
              "high": 66000.0 + i,
              "low": 63000.0 + i,
              "close": 65000.0 + i,
              "volume": 10.0,
              "amount": (65000.0 + i) * 10.0,
              "count": 1,
          }
          for i in range(max(1, min(limit, 80)))
      ]

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: CryptoService(
        {
            "crypto": {
                "exchange": "binance",
                "default_quote_currency": "USDT",
                "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                "paper": {
                    "initial_cash": 10000,
                    "max_order_notional": 5000,
                    "max_position_ratio": 1.0,
                    "partial_fill_enabled": False,
                },
            },
            "storage": {
                "db_path": str(tmp_path / "api_paper_state.db"),
                "binance_testnet_credentials_path": str(tmp_path / "api_testnet_credentials.enc"),
                "binance_testnet_key_path": str(tmp_path / "api_testnet.key"),
            },
        }
    )

    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-token"}
            quotes = client.get("/api/v1/crypto/quotes?symbols=BTC/USDT", headers=headers)
            assert quotes.status_code == 200
            assert quotes.json()["items"][0]["source"] == "binance"

            klines = client.get("/api/v1/crypto/klines?symbol=BTC/USDT&period=1h&limit=5", headers=headers)
            assert klines.status_code == 200
            assert klines.json()["items"][0]["close"] == 65000.0

            templates = client.get("/api/v1/crypto/strategies/templates", headers=headers)
            assert templates.status_code == 200
            assert {item["type"] for item in templates.json()["items"]} >= {"dual_ma", "rsi", "macd", "bollinger", "momentum"}

            strategy_payload = {
                "symbols": ["BTC/USDT", "ETH/USDT"],
                "period": "1h",
                "limit": 80,
                "strategies": [
                    {"strategy_id": "btc_ma", "type": "dual_ma", "symbols": ["BTC/USDT"], "weight": 1.0},
                    {"strategy_id": "eth_momentum", "type": "momentum", "symbols": ["ETH/USDT"], "weight": 0.8},
                ],
            }
            signals = client.post("/api/v1/crypto/strategies/run", headers=headers, json=strategy_payload)
            assert signals.status_code == 200
            assert signals.json()["strategy_results"][0]["strategy_id"] == "btc_ma"

            backtest = client.post("/api/v1/crypto/strategies/backtest", headers=headers, json=strategy_payload)
            assert backtest.status_code == 200
            assert backtest.json()["count"] == 2
            first_backtest = backtest.json()["items"][0]
            assert "drawdown_curve" in first_backtest
            assert "calmar_ratio" in first_backtest
            assert "win_rate" in first_backtest
            assert "profit_factor" in first_backtest
            assert "diagnostics" in first_backtest

            order = client.post(
                "/api/v1/crypto/paper/orders",
                headers=headers,
                json={"symbol": "BTC/USDT", "action": "BUY", "quantity": 0.001, "price": 1000},
            )
            assert order.status_code == 200
            assert order.json()["status"] == "filled"

            portfolio = client.post(
                "/api/v1/crypto/portfolio/returns",
                headers=headers,
                json={"mode": "live", "range": "all", "limit": 50},
            )
            assert portfolio.status_code == 200
            assert "summary" in portfolio.json()
            assert "equity_curve" in portfolio.json()

            testnet_status = client.get("/api/v1/crypto/testnet/status", headers=headers)
            assert testnet_status.status_code == 200
            assert testnet_status.json()["has_api_key"] is False

            testnet_dry_run = client.post(
                "/api/v1/crypto/testnet/orders",
                headers=headers,
                json={"symbol": "BTC/USDT", "action": "BUY", "quantity": 0.001, "price": 1000, "dry_run": True},
            )
            assert testnet_dry_run.status_code == 200
            assert testnet_dry_run.json()["status"] == "dry_run"

            removed_quotes_path = "/api/v1/" + "market" + "/quotes"
            removed_manual_order_path = "/api/v1/" + "trade" + "/manual"
            assert client.get(removed_quotes_path, headers=headers).status_code == 404
            assert client.post(
                removed_manual_order_path,
                headers=headers,
                json={"symbol": "LEGACY", "action": "BUY", "quantity": 100, "price": 10},
            ).status_code == 404
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()


def test_crypto_market_cache_fallback(monkeypatch, tmp_path):
    storage_path = tmp_path / "market_cache.db"
    service = CryptoService(
        {
            "crypto": {"exchange": "binance", "default_quote_currency": "USDT", "symbols": ["BTC/USDT"]},
            "storage": {"db_path": str(storage_path)},
        }
    )

    def fake_quotes(self, symbols):
        return [
            {
                "symbol": "BTC/USDT",
                "price": 65000.0,
                "open": 64000.0,
                "high": 66000.0,
                "low": 63000.0,
                "volume": 10.0,
                "amount": 650000.0,
                "change": 0.015625,
                "change_amount": 1000.0,
                "bid": 64999.0,
                "ask": 65001.0,
                "timestamp": "2026-05-12T00:00:00Z",
                "source": "binance",
            }
        ]

    def fake_ohlcv(self, symbol, timeframe="1h", limit=200):
        return [
            {
                "symbol": "BTC/USDT",
                "period": timeframe,
                "start_time": "2026-05-12T00:00:00Z",
                "end_time": "2026-05-12T00:59:59Z",
                "open": 64000.0,
                "high": 66000.0,
                "low": 63000.0,
                "close": 65000.0,
                "volume": 10.0,
                "amount": 650000.0,
                "count": 1,
            }
        ]

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fake_ohlcv)

    import asyncio

    quotes = asyncio.run(service.get_quotes(["BTC/USDT"]))
    klines = asyncio.run(service.get_klines("BTC/USDT", "1h", 5))
    assert quotes.source == "binance"
    assert klines.source == "binance"

    def fail_quotes(self, symbols):
        raise RuntimeError("network down")

    def fail_ohlcv(self, symbol, timeframe="1h", limit=200):
        raise RuntimeError("network down")

    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", fail_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", fail_ohlcv)

    cached_quotes = asyncio.run(service.get_quotes(["BTC/USDT"]))
    cached_klines = asyncio.run(service.get_klines("BTC/USDT", "1h", 5))
    assert cached_quotes.source == "cache_binance"
    assert cached_quotes.items[0].price == 65000.0
    assert cached_klines.source == "cache_binance"
    assert cached_klines.items[0].close == 65000.0


def test_crypto_strategy_engine_multi_strategy_aggregation_and_backtest():
    engine = CryptoStrategyEngine()
    candles = [
        {
            "symbol": "BTC/USDT",
            "period": "1h",
            "start_time": f"2026-05-12T{i:02d}:00:00Z",
            "end_time": f"2026-05-12T{i:02d}:59:59Z",
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 10,
            "amount": (100 + i) * 10,
            "count": 1,
        }
        for i in range(80)
    ]
    configs = engine.normalize_configs(
        [
            {"strategy_id": "ma", "type": "dual_ma", "symbols": ["BTC/USDT"], "weight": 1.0},
            {"strategy_id": "momentum", "type": "momentum", "symbols": ["BTC/USDT"], "weight": 0.8},
            {"strategy_id": "macd", "type": "macd", "symbols": ["BTC/USDT"], "weight": 1.0},
        ],
        ["BTC/USDT"],
    )
    result = engine.run({"BTC/USDT": candles}, configs)
    assert result["signals"]
    assert result["summary"][0]["symbol"] == "BTC/USDT"
    assert result["summary"][0]["action"] in {"BUY", "SELL", "HOLD"}

    backtests = engine.backtest(
        {"BTC/USDT": candles},
        configs,
        initial_cash=10000,
        fee_rate=0.001,
        slippage_rate=0.0005,
        min_quantity=0.000001,
        period="1h",
    )
    assert len(backtests) == 3
    assert all(item["strategy_id"] in {"ma", "momentum", "macd"} for item in backtests)
    assert all("drawdown_curve" in item for item in backtests)
    assert all("calmar_ratio" in item for item in backtests)


def test_crypto_backtest_engine_decimal_usdt_metrics_and_24_7():
    strategy_engine = CryptoStrategyEngine()
    candles = [
        {
            "symbol": "BTC/USDT",
            "period": "1h",
            "start_time": f"2026-05-{16 + (i // 24):02d}T{i % 24:02d}:00:00Z",
            "end_time": f"2026-05-{16 + (i // 24):02d}T{i % 24:02d}:59:59Z",
            "open": 100 + (i % 12) * 2,
            "high": 103 + (i % 12) * 2,
            "low": 99 + (i % 12) * 2,
            "close": 100 + (i % 12) * 2,
            "volume": 10,
            "amount": (100 + (i % 12) * 2) * 10,
            "count": 1,
        }
        for i in range(96)
    ]
    configs = strategy_engine.normalize_configs(
        [
            {
                "strategy_id": "rsi_cycle",
                "type": "rsi",
                "symbols": ["BTC/USDT"],
                "parameters": {"period": 6, "oversold": 45, "overbought": 55, "position_ratio": 0.5},
            }
        ],
        ["BTC/USDT"],
    )
    engine = CryptoBacktestEngine(initial_cash=10000, fee_rate=0.001, slippage_rate=0.001, min_quantity=0.000001, period="1h")
    result = engine.run({"BTC/USDT": candles}, configs[0])

    assert len(result["equity_curve"]) == len(candles)
    assert len(result["drawdown_curve"]) == len(candles)
    assert result["quote_currency"] == "USDT"
    assert {"sharpe_ratio", "max_drawdown_percent", "calmar_ratio", "win_rate", "profit_factor"} <= set(result)
    if result["trades"]:
        first = result["trades"][0]
        assert first["quantity"] > 0
        assert first["quantity"] != int(first["quantity"])
        assert first["fee"] > 0
        assert first["slippage"] >= 0
        assert first["fill_price"] != first["price"]


def test_crypto_parameter_optimizer_uses_crypto_backtest_and_symbols():
    history = [
        {
            "symbol": "BTC/USDT",
            "period": "1h",
            "start_time": f"2026-05-12T{i:02d}:00:00Z",
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 10,
            "amount": (100 + i) * 10,
        }
        for i in range(80)
    ]
    optimizer = CryptoStrategyParameterOptimizer()
    candidates = optimizer.optimize(
        "momentum",
        {"symbols": ["BTC/USDT"], "parameters": {"position_ratio": 0.2}},
        history,
        {"lookback_period": [5, 10], "buy_threshold": [0.01, 0.03]},
        objective="total_return_percent",
        top_n=2,
        period="1h",
    )

    assert len(candidates) == 2
    assert candidates[0].score >= candidates[-1].score
    assert candidates[0].metrics["symbols"] == ["BTC/USDT"]


def test_binance_stream_message_normalization():
    url = build_binance_stream_url(["BTC/USDT", "ETH/USDT"], period="1h", depth_limit=20, selected_symbol="BTC/USDT")
    assert "btcusdt@ticker" in url
    assert "ethusdt@ticker" in url
    assert "btcusdt@kline_1h" in url
    assert "btcusdt@depth20@1000ms" in url

    ticker = normalize_binance_stream_message(
        {
            "stream": "btcusdt@ticker",
            "data": {
                "e": "24hrTicker",
                "E": 1770000000000,
                "s": "BTCUSDT",
                "c": "65000",
                "o": "64000",
                "h": "66000",
                "l": "63000",
                "v": "10",
                "q": "650000",
                "p": "1000",
                "P": "1.5625",
                "b": "64999",
                "a": "65001",
            },
        }
    )
    assert ticker["type"] == "crypto_ticker"
    assert ticker["item"]["symbol"] == "BTC/USDT"
    assert ticker["item"]["change"] == 0.015625

    kline = normalize_binance_stream_message(
        {
            "stream": "btcusdt@kline_1h",
            "data": {
                "e": "kline",
                "k": {
                    "s": "BTCUSDT",
                    "i": "1h",
                    "t": 1770000000000,
                    "T": 1770003599999,
                    "o": "64000",
                    "h": "66000",
                    "l": "63000",
                    "c": "65000",
                    "v": "10",
                    "q": "650000",
                    "n": 120,
                },
            },
        }
    )
    assert kline["type"] == "crypto_kline"
    assert kline["item"]["period"] == "1h"
    assert kline["item"]["close"] == 65000.0

    depth = normalize_binance_stream_message(
        {
            "stream": "btcusdt@depth20@1000ms",
            "data": {"lastUpdateId": 1, "bids": [["64999", "0.2"]], "asks": [["65001", "0.3"]]},
        }
    )
    assert depth["type"] == "crypto_depth"
    assert depth["item"]["bids"][0] == [64999.0, 0.2]

    shutdown = normalize_binance_stream_message(
        {
            "stream": "btcusdt@ticker",
            "data": {"e": "serverShutdown", "E": 1770000000000},
        }
    )
    assert shutdown["type"] == "crypto_status"
    assert shutdown["state"] == "reconnecting"


def test_crypto_websocket_auth_and_status(monkeypatch, tmp_path):
    auth_service = AuthService(storage_path=str(tmp_path / "auth.db"))
    session = auth_service.bootstrap_user(username="tester", password="password123", display_name="Tester")

    async def fake_stream(websocket, service, symbols, period="1h", depth_limit=20, selected_symbol=None, proxy=None):
        await websocket.send_json(
            {
                "type": "crypto_status",
                "state": "connected",
                "message": "fake stream connected",
            }
        )

    async def fake_snapshots(websocket, service, symbols, period, selected_symbol, depth_limit):
        await websocket.send_json(
            {
                "type": "crypto_ticker",
                "item": {
                    "symbol": "BTC/USDT",
                    "price": 65000,
                    "open": 64000,
                    "high": 66000,
                    "low": 63000,
                    "volume": 10,
                    "amount": 650000,
                    "change": 0.015625,
                    "change_amount": 1000,
                    "bid": 64999,
                    "ask": 65001,
                    "timestamp": "2026-05-12T00:00:00Z",
                    "source": "test",
                },
            }
        )

    monkeypatch.setattr(crypto_ws, "stream_binance_market", fake_stream)
    monkeypatch.setattr(crypto_ws, "send_initial_market_snapshots", fake_snapshots)
    monkeypatch.setattr(dependencies, "get_auth_service", lambda: auth_service)
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_crypto_service] = lambda: CryptoService(
        {
            "crypto": {"exchange": "binance", "symbols": ["BTC/USDT"]},
            "storage": {"db_path": str(tmp_path / "market.db")},
        }
    )

    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/crypto?symbols=BTC/USDT&period=1h") as websocket:
                websocket.send_json({"action": "auth", "token": session.access_token})
                assert websocket.receive_json()["type"] == "auth_ok"
                assert websocket.receive_json()["type"] == "crypto_status"
                assert websocket.receive_json()["type"] == "crypto_ticker"
                status = websocket.receive_json()
                assert status["type"] == "crypto_status"
                assert status["state"] == "connected"
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
