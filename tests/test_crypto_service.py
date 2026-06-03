import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.error_codes import ApiError, ErrorCode
from api.models.request import AiSignalAnalyzeRequest, AutoTradingConfigRequest, CryptoPaperOrderRequest
from api.models.response import CryptoKLineResponse, CryptoKLinesResponse, CryptoQuoteResponse, CryptoQuotesResponse, MacroOverviewResponse
from api.services.crypto_service import CryptoService
from core.macro_data_provider import MacroSnapshot


def _service(tmp_path, config=None):
    payload = config or {"crypto": {"symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]}}
    payload.setdefault("storage", {"db_path": str(tmp_path / "service.db")})
    return CryptoService(payload)


def _quote(symbol="BTC/USDT", price=65000):
    return {
        "symbol": symbol,
        "price": price,
        "open": price - 100,
        "high": price + 100,
        "low": price - 200,
        "volume": 10,
        "amount": price * 10,
        "change": 0.01,
        "change_amount": 100,
        "bid": price - 1,
        "ask": price + 1,
        "timestamp": "2026-06-03T00:00:00Z",
        "source": "binance",
    }


def _kline(symbol="BTC/USDT", close=65000):
    return {
        "symbol": symbol,
        "period": "1h",
        "start_time": "2026-06-03T00:00:00Z",
        "end_time": "2026-06-03T00:59:59Z",
        "open": close - 100,
        "high": close + 100,
        "low": close - 200,
        "close": close,
        "volume": 10,
        "amount": close * 10,
        "count": 1,
    }


def _advice(action="BUY", confidence=0.8, notional=200, symbol="BTC/USDT"):
    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "suggested_notional_usdt": notional,
        "max_loss_usdt": 20,
        "time_horizon": "1h",
        "reason": "unit",
        "risk_notes": ["risk"],
        "invalid_if": ["invalid"],
    }


def _ai_record(**overrides):
    payload = {
        "signal_id": "AI_BTC_1",
        "symbol": "BTC/USDT",
        "period": "1h",
        "model": "test-model",
        "request_summary": {},
        "response": _advice(),
        "action": "BUY",
        "confidence": 0.8,
        "approval_status": "approved",
        "approval_reason": "ok",
        "approved_notional_usdt": 200,
        "linked_order_id": "",
        "created_at": "2026-06-03T00:00:00Z",
        "updated_at": "2026-06-03T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _save_ai_record(**kwargs):
    response = kwargs.get("response") or _advice()
    return _ai_record(
        symbol=kwargs.get("symbol", response.get("symbol", "BTC/USDT")),
        period=kwargs.get("period", "1h"),
        model=kwargs.get("model", "test-model"),
        request_summary=kwargs.get("request_summary", {}),
        response=response,
        action=response.get("action", "BUY"),
        confidence=response.get("confidence", 0.8),
        approval_status=kwargs.get("approval_status", "approved"),
        approval_reason=kwargs.get("approval_reason", "ok"),
        approved_notional_usdt=kwargs.get("approved_notional_usdt", 0),
    )


def test_init_symbols_components_and_auto_config(tmp_path):
    service = _service(tmp_path, {"crypto": {"symbols": ["btc/usdt", "BTC/USDT"]}, "risk": {"max_order_notional": 500}})

    assert service.default_symbols == ["BTC/USDT"]
    for attr in [
        "provider",
        "market_cache",
        "paper_broker",
        "strategy_engine",
        "auto_trading_engine",
        "shadow_engine",
        "macro_evaluator",
        "ai_advisor",
        "ai_store",
    ]:
        assert getattr(service, attr) is not None
    assert service.auto_trading_engine.config.max_order_notional == 500
    assert service._macro_cache is None
    assert service._macro_cache_time == 0.0


def test_get_quotes_specific_all_search_pagination_and_cache(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_quotes = MagicMock(return_value=[_quote("BTC/USDT"), _quote("ETH/USDT", 3000)])
    service.provider.fetch_all_tickers = MagicMock(return_value=[_quote("BTC/USDT"), _quote("ETH/USDT", 3000), _quote("SOL/USDT", 150)])
    service.market_cache.upsert_quotes = MagicMock()

    specific = asyncio.run(service.get_quotes(["BTC/USDT", "ETH/USDT"]))
    assert specific.count == 2
    assert specific.source == "binance"
    service.provider.fetch_quotes.assert_called_once()
    service.market_cache.upsert_quotes.assert_called()

    all_rows = asyncio.run(service.get_quotes(None, search="btc", limit=1, offset=0))
    assert all_rows.count == 1
    assert all_rows.total == 1
    assert all_rows.items[0].symbol == "BTC/USDT"
    service.provider.fetch_all_tickers.assert_called()

    empty = asyncio.run(service.get_quotes([]))
    assert empty.items == []
    assert empty.count == 0

    service.provider.fetch_quotes = MagicMock(side_effect=RuntimeError("network"))
    service.market_cache.get_quotes = MagicMock(return_value=[_quote("BTC/USDT")])
    cached = asyncio.run(service.get_quotes(["BTC/USDT"]))
    assert cached.source == "cache_binance"

    service.market_cache.get_quotes = MagicMock(return_value=[])
    with pytest.raises(ApiError) as exc_info:
        asyncio.run(service.get_quotes(["BTC/USDT"]))
    assert exc_info.value.status_code == 503


def test_get_available_symbols_cache_and_market_load(tmp_path):
    service = _service(tmp_path)
    service.market_cache.get_symbols = MagicMock(side_effect=[([{"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "status": "active"}], 1)])
    cached = asyncio.run(service.get_available_symbols(quote="USDT", search="BTC", limit=50, offset=100))
    assert cached.total == 1
    service.market_cache.get_symbols.assert_called_with(quote="USDT", search="BTC", status="active", limit=50, offset=100)

    service.market_cache.get_symbols = MagicMock(side_effect=[([], 0), ([{"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "status": "active"}], 1)])
    service.provider.load_markets = MagicMock(return_value={"ETH/USDT": {"symbol": "ETH/USDT"}})
    service.market_cache.upsert_exchange_info = MagicMock()
    loaded = asyncio.run(service.get_available_symbols())
    assert loaded.total == 1
    service.market_cache.upsert_exchange_info.assert_called_once()

    service.market_cache.get_symbols = MagicMock(return_value=([], 0))
    service.provider.load_markets = MagicMock(side_effect=RuntimeError("down"))
    failed = asyncio.run(service.get_available_symbols())
    assert failed.total == 0


def test_get_klines_and_orderbook_success_fallback_errors(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(return_value=[_kline()])
    service.market_cache.upsert_klines = MagicMock()
    klines = asyncio.run(service.get_klines("BTC/USDT", "1h", 10))
    assert klines.count == 1
    assert klines.source == "binance"
    service.market_cache.upsert_klines.assert_called_once()

    service.provider.fetch_ohlcv = MagicMock(side_effect=RuntimeError("network"))
    service.market_cache.get_klines = MagicMock(return_value=[_kline()])
    cached = asyncio.run(service.get_klines("BTC/USDT", "1h", 10))
    assert cached.source == "cache_binance"

    service.market_cache.get_klines = MagicMock(return_value=[])
    with pytest.raises(ApiError) as unavailable:
        asyncio.run(service.get_klines("BTC/USDT", "1h", 10))
    assert unavailable.value.status_code == 503

    service.provider.fetch_ohlcv = MagicMock(side_effect=ValueError("bad period"))
    with pytest.raises(ApiError) as bad_period:
        asyncio.run(service.get_klines("BTC/USDT", "bad", 10))
    assert bad_period.value.status_code == 400

    with pytest.raises(ApiError):
        asyncio.run(service.get_klines("", "1h", 10))

    service.provider.fetch_order_book = MagicMock(return_value={"symbol": "BTC/USDT", "bids": [[1, 2]], "asks": [[2, 3]], "timestamp": ""})
    book = asyncio.run(service.get_orderbook("BTC/USDT"))
    assert book.bids[0] == [1, 2]
    service.provider.fetch_order_book = MagicMock(side_effect=RuntimeError("down"))
    with pytest.raises(ApiError):
        asyncio.run(service.get_orderbook("BTC/USDT"))
    with pytest.raises(ApiError):
        asyncio.run(service.get_orderbook(""))


def test_paper_order_account_positions_logs_and_auto_controls(tmp_path):
    service = _service(tmp_path, {"crypto": {"paper": {"partial_fill_enabled": False, "max_position_ratio": 1.0}}, "storage": {"db_path": str(tmp_path / "paper.db")}})
    buy = asyncio.run(service.place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.01, price=50000)))
    assert buy.status == "filled"
    assert asyncio.run(service.get_paper_account()).initial_cash == 10000
    assert asyncio.run(service.get_paper_positions()).count == 1
    assert asyncio.run(service.get_paper_equity_curve()).count > 0
    assert asyncio.run(service.get_paper_logs()).count > 0
    assert asyncio.run(service.get_paper_orders(limit=2, offset=0)).total == 1
    assert asyncio.run(service.cancel_paper_order("bad"))["success"] is False

    sell_rejected = asyncio.run(service.place_paper_order(CryptoPaperOrderRequest(symbol="ETH/USDT", action="SELL", quantity=1, price=1000)))
    assert sell_rejected.status == "rejected"

    service.run_strategies = MagicMock(return_value=None)
    service.auto_trading_engine.start()
    status = asyncio.run(service.get_auto_trading_status())
    assert status.mode == "paper"
    updated = asyncio.run(service.update_auto_trading_config(AutoTradingConfigRequest(scan_interval_seconds=60)))
    assert updated.config["scan_interval_seconds"] == 60
    assert asyncio.run(service.get_auto_trading_logs(limit=50)).count <= 50


def test_paper_orders_pagination_cancel_success_and_account_initial(tmp_path):
    service = _service(
        tmp_path,
        {
            "crypto": {"paper": {"partial_fill_enabled": False, "max_position_ratio": 1.0, "max_order_notional": 10000}},
            "storage": {"db_path": str(tmp_path / "paper_page.db")},
        },
    )
    assert asyncio.run(service.get_paper_account()).equity == 10000
    orders = [
        asyncio.run(service.place_paper_order(CryptoPaperOrderRequest(symbol=f"C{index}/USDT", action="BUY", quantity=1, price=100)))
        for index in range(5)
    ]
    page = asyncio.run(service.get_paper_orders(limit=2, offset=1))
    assert page.count == 2
    assert page.total == 5
    assert asyncio.run(service.cancel_paper_order(orders[0].order_id))["success"] is False

    partial_service = _service(
        tmp_path,
        {
            "crypto": {"paper": {"max_position_ratio": 1.0, "max_order_notional": 10000}},
            "storage": {"db_path": str(tmp_path / "paper_partial.db")},
        },
    )
    partial = asyncio.run(partial_service.place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.1, price=50000)))
    assert partial.status == "partial_filled"
    assert asyncio.run(partial_service.cancel_paper_order(partial.order_id))["success"] is True


def test_auto_trading_start_pause_stop_status_update_and_logs(tmp_path):
    async def scenario():
        service = _service(tmp_path, {"auto_trading": {"scan_interval_seconds": 3600}, "storage": {"db_path": str(tmp_path / "auto.db")}})
        started = await service.start_auto_trading()
        assert started.state == "running"
        assert service._auto_loop_task is not None
        assert not service._auto_loop_task.done()

        status = await service.get_auto_trading_status()
        assert status.state == "running"
        updated = await service.update_auto_trading_config(AutoTradingConfigRequest(scan_interval_seconds=60))
        assert updated.config["scan_interval_seconds"] == 60
        logs = await service.get_auto_trading_logs(limit=50)
        assert logs.count <= 50

        paused = await service.pause_auto_trading()
        assert paused.state == "paused"
        assert service._auto_loop_task is None

        restarted = await service.start_auto_trading()
        assert restarted.state == "running"
        stopped = await service.stop_auto_trading()
        assert stopped.state == "stopped"
        assert service._auto_loop_task is None

    asyncio.run(scenario())


def test_macro_overview_cache_and_connection_health(tmp_path):
    service = _service(tmp_path)
    snapshot = MacroSnapshot(timestamp="2026-06-03T00:00:00Z")
    service.macro_provider.fetch_snapshot = MagicMock(return_value=snapshot)
    service.macro_evaluator.evaluate = MagicMock(return_value=MagicMock(to_dict=lambda: {"state": "ALLOW_FULL"}))

    first = asyncio.run(service.get_macro_overview())
    second = asyncio.run(service.get_macro_overview())
    assert first == second
    assert service.macro_provider.fetch_snapshot.call_count == 1
    service._macro_cache_time -= 301
    asyncio.run(service.get_macro_overview())
    assert service.macro_provider.fetch_snapshot.call_count == 2

    service.provider.get_connection_health = MagicMock(return_value={"quotes": {"state": "closed"}})
    assert asyncio.run(service.get_connection_health()).quotes.state == "closed"


def test_ai_assess_advice_rules_and_helpers(tmp_path):
    service = _service(tmp_path, {"ai": {"min_confidence_for_order": 0.65, "max_order_notional": 300}, "risk": {"max_order_notional": 150}})
    account = {"available_cash": 200, "cash": 200}

    assert service._assess_ai_advice(_advice("HOLD"), account, [])["approval_status"] == "blocked"
    assert service._assess_ai_advice(_advice("TRANSFER"), account, [])["approval_status"] == "blocked"
    assert service._assess_ai_advice(_advice("BUY", confidence=0.3), account, [])["approval_status"] == "blocked"
    assert service._assess_ai_advice(_advice("BUY", notional=0), account, [])["approval_status"] == "blocked"
    assert service._assess_ai_advice(_advice("BUY", notional=500), account, [])["approved_notional_usdt"] == 150
    assert service._assess_ai_advice(_advice("SELL", notional=500), account, [])["approval_status"] == "blocked"
    assert service._assess_ai_advice(_advice("SELL", notional=500), account, [{"symbol": "btc/usdt", "available": 0.1}])["approval_status"] == "approved"

    assert service._assess_ai_advice(_advice("BUY"), {"real_trading_enabled": True}, [])["approval_status"] == "blocked"
    service.config["risk"] = {"allow_leverage": True}
    assert "leverage" in service._assess_ai_advice(_advice("BUY"), account, [])["approval_reason"]
    service.config["risk"] = {"allow_short_selling": True}
    assert "short selling" in service._assess_ai_advice(_advice("SELL"), account, [{"symbol": "BTC/USDT", "quantity": 1}])["approval_reason"]

    assert service._normalize_symbols(["btc/usdt", "BTC/USDT", ""]) == ["BTC/USDT"]
    assert service._position_quantity("BTC/USDT", [{"symbol": "btc/usdt", "available": 1.5}]) == 1.5
    assert service._position_quantity("BTC/USDT", [{"symbol": "BTC/USDT", "quantity": 2.0}]) == 2.0
    assert service._position_quantity("ETH/USDT", []) == 0.0


def test_ai_assess_real_trading_flags_cash_caps_and_position_caps(tmp_path):
    assert _service(tmp_path, {"risk": {"real_trading_enabled": True}})._assess_ai_advice(_advice(), {"cash": 1000}, [])["approval_status"] == "blocked"
    assert _service(tmp_path, {"trading": {"real_trading_enabled": True}})._assess_ai_advice(_advice(), {"cash": 1000}, [])["approval_status"] == "blocked"
    assert _service(tmp_path, {"crypto": {"paper": {"real_trading_enabled": True}}})._assess_ai_advice(_advice(), {"cash": 1000}, [])["approval_status"] == "blocked"
    assert _service(tmp_path, {"crypto": {"testnet": {"real_trading_enabled": True}}})._assess_ai_advice(_advice(), {"cash": 1000}, [])["approval_status"] == "blocked"
    assert _service(tmp_path, {"crypto": {"mainnet": {"real_trading_enabled": True}}})._assess_ai_advice(_advice(), {"cash": 1000}, [])["approval_status"] == "blocked"

    cash_cap = _service(tmp_path, {"ai": {"max_order_notional": 300}})._assess_ai_advice(_advice("BUY", notional=500), {"available_cash": 200}, [])
    assert cash_cap["approval_status"] == "approved"
    assert cash_cap["approved_notional_usdt"] == 200

    ai_cap = _service(tmp_path, {"ai": {"max_order_notional": 300}})._assess_ai_advice(_advice("BUY", notional=500), {"available_cash": 1000}, [])
    assert ai_cap["approved_notional_usdt"] == 300
    assert _service(tmp_path, {"ai": {"max_order_notional": 300}})._assess_ai_advice(_advice("BUY"), {"available_cash": 0}, [])["approval_status"] == "blocked"
    assert _service(tmp_path, {"ai": {"max_order_notional": 300}, "crypto": {"paper": {"max_order_notional": 100}}})._assess_ai_advice(
        _advice("BUY", notional=500), {"available_cash": 1000}, []
    )["approved_notional_usdt"] == 100


def test_ai_signal_analyze_list_get_and_provider_failures(tmp_path):
    service = _service(tmp_path, {"ai": {"enabled": True, "min_confidence_for_order": 0.65, "max_order_notional": 300}, "storage": {"db_path": str(tmp_path / "ai.db")}})
    service.get_quotes = AsyncMock(return_value=CryptoQuotesResponse(items=[CryptoQuoteResponse(**_quote())], count=1, source="unit"))
    service.get_klines = AsyncMock(return_value=CryptoKLinesResponse(symbol="BTC/USDT", period="1h", items=[CryptoKLineResponse(**_kline())], count=1))
    service.get_macro_overview = AsyncMock(return_value=MacroOverviewResponse(data={}, gate={"state": "ALLOW_FULL"}))
    service.paper_broker.get_account_info = MagicMock(return_value={"cash": 1000, "available_cash": 1000})
    service.paper_broker.get_positions = MagicMock(return_value=[])
    service.paper_broker.get_orders = MagicMock(return_value={"items": []})
    service.ai_advisor.analyze = MagicMock(return_value=_advice("BUY", 0.8, 200))
    service.ai_store.save_signal = MagicMock(return_value=_ai_record())

    result = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=30)))
    assert result.signal.approval_status == "approved"

    service.ai_advisor.analyze = MagicMock(side_effect=ValueError("bad json"))
    service.ai_store.save_signal = MagicMock(return_value=_ai_record(approval_status="failed", approval_reason="bad json"))
    failed = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=30)))
    assert failed.signal.approval_status == "failed"

    service.ai_advisor.analyze = MagicMock(side_effect=RuntimeError("no provider"))
    with pytest.raises(ApiError) as unavailable:
        asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=30)))
    assert unavailable.value.detail["error_code"] == ErrorCode.AI_PROVIDER_UNAVAILABLE

    service.ai_store.list_signals = MagicMock(return_value={"items": [_ai_record()], "count": 1, "total": 1, "limit": 10, "offset": 0})
    assert asyncio.run(service.list_ai_signals(limit=10)).count == 1
    service.ai_store.get_signal = MagicMock(return_value=_ai_record())
    assert asyncio.run(service.get_ai_signal("AI_BTC_1")).signal_id == "AI_BTC_1"
    service.ai_store.get_signal = MagicMock(return_value=None)
    with pytest.raises(ApiError):
        asyncio.run(service.get_ai_signal("missing"))


def test_analyze_ai_signal_hold_low_confidence_buy_and_sell_no_position(tmp_path):
    service = _service(tmp_path, {"ai": {"enabled": True, "min_confidence_for_order": 0.65, "max_order_notional": 300}, "storage": {"db_path": str(tmp_path / "ai_cases.db")}})
    service.get_quotes = AsyncMock(return_value=CryptoQuotesResponse(items=[CryptoQuoteResponse(**_quote())], count=1, source="unit"))
    service.get_klines = AsyncMock(return_value=CryptoKLinesResponse(symbol="BTC/USDT", period="1h", items=[CryptoKLineResponse(**_kline())], count=1))
    service.get_macro_overview = AsyncMock(return_value=MacroOverviewResponse(data={}, gate={"state": "ALLOW_FULL"}))
    service.paper_broker.get_account_info = MagicMock(return_value={"cash": 1000, "available_cash": 1000})
    service.paper_broker.get_positions = MagicMock(return_value=[])
    service.paper_broker.get_orders = MagicMock(return_value={"items": []})
    service.ai_store.save_signal = MagicMock(side_effect=lambda **kwargs: _save_ai_record(**kwargs))

    for advice, expected_status, expected_reason in [
        (_advice("HOLD", 0.8, 0), "blocked", "HOLD"),
        (_advice("BUY", 0.3, 200), "blocked", "confidence"),
        (_advice("BUY", 0.8, 200), "approved", "approved"),
        (_advice("SELL", 0.8, 200), "blocked", "no position to sell"),
    ]:
        service.ai_advisor.analyze = MagicMock(return_value=advice)
        result = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=30)))
        assert result.signal.approval_status == expected_status
        assert expected_reason in result.signal.approval_reason
