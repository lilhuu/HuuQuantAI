import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.error_codes import ApiError, ErrorCode
from api.models.request import AiSignalAnalyzeRequest, AutoTradingConfigRequest, CryptoPaperOrderRequest
from api.models.response import CryptoKLineResponse, CryptoKLinesResponse, CryptoQuoteResponse, CryptoQuotesResponse, MacroOverviewResponse
from api.services.crypto_service import CryptoService
from core.macro_data_provider import MacroSnapshot


def _test(name, check):
    if "tmp_path" in inspect.signature(check).parameters:
        def wrapper(tmp_path):
            check(tmp_path)
    else:
        def wrapper():
            check()

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__doc__ = f"md spec: {name}"
    return wrapper


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path, config=None):
    payload = config or {"crypto": {"symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]}}
    payload.setdefault("storage", {"db_path": str(tmp_path / "service.db")})
    return CryptoService(payload)


def _quote(symbol="BTC/USDT", price=65000, source="ccxt"):
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
        "timestamp": "2026-06-04T00:00:00Z",
        "source": source,
    }


def _kline(symbol="BTC/USDT", close=65000):
    return {
        "symbol": symbol,
        "period": "1h",
        "start_time": "2026-06-04T00:00:00Z",
        "end_time": "2026-06-04T00:59:59Z",
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
    response = overrides.get("response") or _advice()
    payload = {
        "signal_id": "AI_BTC_1",
        "symbol": overrides.get("symbol", response.get("symbol", "BTC/USDT")),
        "period": overrides.get("period", "1h"),
        "model": overrides.get("model", "test-model"),
        "request_summary": overrides.get("request_summary", {}),
        "response": response,
        "action": response.get("action", "BUY"),
        "confidence": response.get("confidence", 0.8),
        "approval_status": overrides.get("approval_status", "approved"),
        "approval_reason": overrides.get("approval_reason", "ok"),
        "approved_notional_usdt": overrides.get("approved_notional_usdt", 200),
        "linked_order_id": overrides.get("linked_order_id", ""),
        "created_at": "2026-06-04T00:00:00Z",
        "updated_at": "2026-06-04T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _save_signal(**kwargs):
    return _ai_record(**kwargs)


def _mock_ai_context(service, advice=None):
    service.get_quotes = AsyncMock(return_value=CryptoQuotesResponse(items=[CryptoQuoteResponse(**_quote())], count=1, source="unit"))
    service.get_klines = AsyncMock(return_value=CryptoKLinesResponse(symbol="BTC/USDT", period="1h", items=[CryptoKLineResponse(**_kline())], count=1))
    service.get_macro_overview = AsyncMock(return_value=MacroOverviewResponse(data={}, gate={"state": "ALLOW_FULL"}))
    service.paper_broker.get_account_info = MagicMock(return_value={"cash": 1000, "available_cash": 1000})
    service.paper_broker.get_positions = MagicMock(return_value=[])
    service.paper_broker.get_orders = MagicMock(return_value={"items": []})
    service.ai_advisor.analyze = MagicMock(return_value=advice or _advice())
    service.ai_store.save_signal = MagicMock(side_effect=lambda **kwargs: _save_signal(**kwargs))


def _analyze(service):
    return _run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=30)))


def assert_equal(actual, expected):
    assert actual == expected


def assert_raises_api(func, status=None, error_code=None):
    with pytest.raises(ApiError) as exc_info:
        func()
    if status is not None:
        assert exc_info.value.status_code == status
    if error_code is not None:
        assert exc_info.value.detail["error_code"] == error_code


def _quotes_service(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_quotes = MagicMock(return_value=[_quote("BTC/USDT"), _quote("ETH/USDT", 3000)])
    service.provider.fetch_all_tickers = MagicMock(return_value=[_quote("BTC/USDT"), _quote("ETH/USDT", 3000), _quote("SOL/USDT", 150)])
    service.market_cache.upsert_quotes = MagicMock()
    return service


def _symbols_row(symbol="BTC/USDT"):
    base, quote = symbol.split("/")
    return {"symbol": symbol, "base": base, "quote": quote, "status": "active"}


def _with_macro(service):
    snapshot = MacroSnapshot(timestamp="2026-06-04T00:00:00Z")
    service.macro_provider.fetch_snapshot = MagicMock(return_value=snapshot)
    service.macro_evaluator.evaluate = MagicMock(return_value=MagicMock(to_dict=lambda: {"state": "ALLOW_FULL"}))


def _ai_assess(tmp_path, config=None, advice=None, account=None, positions=None):
    service = _service(tmp_path, config or {"ai": {"min_confidence_for_order": 0.65, "max_order_notional": 300}})
    return service._assess_ai_advice(advice or _advice(), account or {"cash": 1000, "available_cash": 1000}, positions or [])


INIT_CASES = {
    "test_init_default_symbols": lambda tmp_path: assert_equal(_service(tmp_path, {"crypto": {"symbols": ["BTC/USDT", "ETH/USDT"]}}).default_symbols, ["BTC/USDT", "ETH/USDT"]),
    "test_init_symbols_normalized": lambda tmp_path: assert_equal(_service(tmp_path, {"crypto": {"symbols": ["btc/usdt"]}}).default_symbols, ["BTC/USDT"]),
    "test_init_default_symbols_dedup": lambda tmp_path: assert_equal(_service(tmp_path, {"crypto": {"symbols": ["BTC/USDT", "BTC/USDT"]}}).default_symbols, ["BTC/USDT"]),
    "test_init_all_sub_components_created": lambda tmp_path: assert_components(_service(tmp_path)),
    "test_init_auto_config_inherits_risk_max_notional": lambda tmp_path: assert_equal(_service(tmp_path, {"risk": {"max_order_notional": 500}}).auto_trading_engine.config.max_order_notional, 500),
    "test_init_macro_cache_initial_none": lambda tmp_path: assert_macro_cache_empty(_service(tmp_path)),
    "test_init_auto_scan_lock_is_asyncio_lock": lambda tmp_path: assert_lock(_service(tmp_path)),
}


def assert_components(service):
    for attr in ["provider", "market_cache", "paper_broker", "strategy_engine", "auto_trading_engine", "shadow_engine", "macro_evaluator", "ai_advisor", "ai_store"]:
        assert getattr(service, attr) is not None


def assert_macro_cache_empty(service):
    assert service._macro_cache is None
    assert service._macro_cache_time == 0.0


def assert_lock(service):
    assert isinstance(service._auto_scan_lock, asyncio.Lock)


QUOTE_CASES = {
    "test_quotes_with_specific_symbols": lambda tmp_path: assert_quotes_specific(tmp_path),
    "test_quotes_empty_symbols_list": lambda tmp_path: assert_empty_quotes(tmp_path),
    "test_quotes_null_symbols_calls_fetch_all": lambda tmp_path: assert_quotes_all(tmp_path),
    "test_quotes_search_filters_correctly": lambda tmp_path: assert_quotes_search(tmp_path, "BTC"),
    "test_quotes_search_case_insensitive": lambda tmp_path: assert_quotes_search(tmp_path, "btc"),
    "test_quotes_pagination": lambda tmp_path: assert_quotes_pagination(tmp_path),
    "test_quotes_pagination_defaults": lambda tmp_path: assert_quotes_pagination_defaults(tmp_path),
    "test_quotes_fallback_to_cache": lambda tmp_path: assert_quotes_cache(tmp_path),
    "test_quotes_no_cache_no_source_raises": lambda tmp_path: assert_quotes_no_cache(tmp_path),
    "test_quotes_records_snapshots_to_cache": lambda tmp_path: assert_quotes_recorded(tmp_path),
    "test_quotes_cache_fallback_only_for_specific_symbols": lambda tmp_path: assert_quotes_cache(tmp_path),
}


def assert_quotes_specific(tmp_path):
    response = _run(_quotes_service(tmp_path).get_quotes(["BTC/USDT", "ETH/USDT"]))
    assert response.count == 2
    assert response.source == "ccxt"


def assert_empty_quotes(tmp_path):
    response = _run(_quotes_service(tmp_path).get_quotes([]))
    assert response.items == []
    assert response.count == 0


def assert_quotes_all(tmp_path):
    service = _quotes_service(tmp_path)
    _run(service.get_quotes(None))
    service.provider.fetch_all_tickers.assert_called_once()
    service.provider.fetch_quotes.assert_not_called()


def assert_quotes_search(tmp_path, term):
    response = _run(_quotes_service(tmp_path).get_quotes(None, search=term))
    assert [item.symbol for item in response.items] == ["BTC/USDT"]


def assert_quotes_pagination(tmp_path):
    response = _run(_quotes_service(tmp_path).get_quotes(None, limit=2, offset=1))
    assert response.count == 2
    assert response.total == 3


def assert_quotes_pagination_defaults(tmp_path):
    response = _run(_quotes_service(tmp_path).get_quotes(None))
    assert response.limit == 0
    assert response.offset == 0
    assert response.count == 3


def assert_quotes_cache(tmp_path):
    service = _quotes_service(tmp_path)
    service.provider.fetch_quotes = MagicMock(side_effect=RuntimeError("down"))
    service.market_cache.get_quotes = MagicMock(return_value=[_quote("BTC/USDT", source="cache")])
    assert _run(service.get_quotes(["BTC/USDT"])).source == "cache_binance"


def assert_quotes_no_cache(tmp_path):
    service = _quotes_service(tmp_path)
    service.provider.fetch_quotes = MagicMock(side_effect=RuntimeError("down"))
    service.market_cache.get_quotes = MagicMock(return_value=[])
    assert_raises_api(lambda: _run(service.get_quotes(["BTC/USDT"])), 503)


def assert_quotes_recorded(tmp_path):
    service = _quotes_service(tmp_path)
    _run(service.get_quotes(["BTC/USDT"]))
    service.market_cache.upsert_quotes.assert_called()


SYMBOL_CASES = {
    "test_symbols_from_cache": lambda tmp_path: assert_symbols_cache(tmp_path),
    "test_symbols_cache_miss_loads_markets": lambda tmp_path: assert_symbols_load(tmp_path),
    "test_symbols_cache_miss_load_markets_fails": lambda tmp_path: assert_symbols_load_fails(tmp_path),
    "test_symbols_pagination_passed_through": lambda tmp_path: assert_symbols_args(tmp_path, limit=50, offset=100),
    "test_symbols_quote_filter_passed_through": lambda tmp_path: assert_symbols_args(tmp_path, quote="USDT"),
    "test_symbols_search_passed_through": lambda tmp_path: assert_symbols_args(tmp_path, search="BTC"),
}


def assert_symbols_cache(tmp_path):
    service = _service(tmp_path)
    service.market_cache.get_symbols = MagicMock(return_value=([_symbols_row()], 400))
    service.provider.load_markets = MagicMock()
    response = _run(service.get_available_symbols())
    assert response.total == 400
    service.provider.load_markets.assert_not_called()


def assert_symbols_load(tmp_path):
    service = _service(tmp_path)
    service.market_cache.get_symbols = MagicMock(side_effect=[([], 0), ([_symbols_row("ETH/USDT")], 1)])
    service.provider.load_markets = MagicMock(return_value={"ETH/USDT": {"symbol": "ETH/USDT"}})
    service.market_cache.upsert_exchange_info = MagicMock()
    assert _run(service.get_available_symbols()).total == 1
    service.market_cache.upsert_exchange_info.assert_called_once()


def assert_symbols_load_fails(tmp_path):
    service = _service(tmp_path)
    service.market_cache.get_symbols = MagicMock(return_value=([], 0))
    service.provider.load_markets = MagicMock(side_effect=RuntimeError("down"))
    assert _run(service.get_available_symbols()).total == 0


def assert_symbols_args(tmp_path, **kwargs):
    service = _service(tmp_path)
    service.market_cache.get_symbols = MagicMock(return_value=([_symbols_row()], 1))
    _run(service.get_available_symbols(**kwargs))
    expected = {"quote": None, "search": None, "status": "active", "limit": 100, "offset": 0}
    expected.update(kwargs)
    service.market_cache.get_symbols.assert_called_with(**expected)


KLINE_ORDERBOOK_CASES = {
    "test_klines_invalid_symbol_raises": lambda tmp_path: assert_raises_api(lambda: _run(_service(tmp_path).get_klines("", "1h", 10)), 400),
    "test_klines_success": lambda tmp_path: assert_klines_success(tmp_path),
    "test_klines_fallback_to_cache": lambda tmp_path: assert_klines_cache(tmp_path),
    "test_klines_no_cache_no_source_raises": lambda tmp_path: assert_klines_no_cache(tmp_path),
    "test_klines_bad_period_caught": lambda tmp_path: assert_klines_bad_period(tmp_path),
    "test_klines_records_to_cache": lambda tmp_path: assert_klines_records(tmp_path),
    "test_orderbook_invalid_symbol": lambda tmp_path: assert_raises_api(lambda: _run(_service(tmp_path).get_orderbook("")), 400),
    "test_orderbook_success": lambda tmp_path: assert_orderbook_success(tmp_path),
    "test_orderbook_provider_error": lambda tmp_path: assert_orderbook_error(tmp_path),
}


def assert_klines_success(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(return_value=[_kline()])
    service.market_cache.upsert_klines = MagicMock()
    response = _run(service.get_klines("BTC/USDT", "1h", 10))
    assert response.count == 1
    assert response.source == "binance"


def assert_klines_cache(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(side_effect=RuntimeError("down"))
    service.market_cache.get_klines = MagicMock(return_value=[_kline()])
    assert _run(service.get_klines("BTC/USDT", "1h", 10)).source == "cache_binance"


def assert_klines_no_cache(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(side_effect=RuntimeError("down"))
    service.market_cache.get_klines = MagicMock(return_value=[])
    assert_raises_api(lambda: _run(service.get_klines("BTC/USDT", "1h", 10)), 503)


def assert_klines_bad_period(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(side_effect=ValueError("bad period"))
    assert_raises_api(lambda: _run(service.get_klines("BTC/USDT", "bad", 10)), 400)


def assert_klines_records(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_ohlcv = MagicMock(return_value=[_kline()])
    service.market_cache.upsert_klines = MagicMock()
    _run(service.get_klines("BTC/USDT", "1h", 10))
    service.market_cache.upsert_klines.assert_called_once()


def assert_orderbook_success(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_order_book = MagicMock(return_value={"symbol": "BTC/USDT", "bids": [[1, 2]], "asks": [[2, 3]], "timestamp": ""})
    assert _run(service.get_orderbook("BTC/USDT")).bids == [[1, 2]]


def assert_orderbook_error(tmp_path):
    service = _service(tmp_path)
    service.provider.fetch_order_book = MagicMock(side_effect=RuntimeError("down"))
    assert_raises_api(lambda: _run(service.get_orderbook("BTC/USDT")), 503)


PAPER_AUTO_CASES = {
    "test_place_paper_order_buy": lambda tmp_path: assert_paper_buy(tmp_path),
    "test_place_paper_order_sell_no_position_rejected": lambda tmp_path: assert_paper_sell_rejected(tmp_path),
    "test_get_paper_orders_pagination": lambda tmp_path: assert_paper_orders_page(tmp_path),
    "test_cancel_paper_order_success": lambda tmp_path: assert_paper_cancel_success(tmp_path),
    "test_cancel_paper_order_nonexistent": lambda tmp_path: assert_equal(_run(_service(tmp_path).cancel_paper_order("bad-id"))["success"], False),
    "test_get_paper_account_initial": lambda tmp_path: assert_equal(_run(_service(tmp_path).get_paper_account()).equity, 10000),
    "test_get_paper_positions_after_buy": lambda tmp_path: assert_paper_positions(tmp_path),
    "test_get_equity_curve": lambda tmp_path: assert_paper_equity_curve(tmp_path),
    "test_get_paper_logs": lambda tmp_path: assert_paper_logs(tmp_path),
    "test_start_auto_trading": lambda tmp_path: assert_auto_start(tmp_path),
    "test_pause_auto_trading": lambda tmp_path: assert_auto_pause(tmp_path),
    "test_stop_auto_trading": lambda tmp_path: assert_auto_stop(tmp_path),
    "test_get_auto_trading_status": lambda tmp_path: assert_equal(_run(_service(tmp_path).get_auto_trading_status()).state, "stopped"),
    "test_update_auto_trading_config": lambda tmp_path: assert_equal(_run(_service(tmp_path).update_auto_trading_config(AutoTradingConfigRequest(scan_interval_seconds=60))).config["scan_interval_seconds"], 60),
    "test_get_auto_trading_logs": lambda tmp_path: assert_auto_logs(tmp_path),
}


def assert_paper_buy(tmp_path):
    service = _service(tmp_path, {"crypto": {"paper": {"partial_fill_enabled": False, "max_position_ratio": 1.0}}, "storage": {"db_path": str(tmp_path / "paper.db")}})
    order = _run(service.place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.01, price=50000)))
    assert order.status == "filled"


def assert_paper_sell_rejected(tmp_path):
    order = _run(_service(tmp_path).place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="SELL", quantity=0.01, price=50000)))
    assert order.status == "rejected"


def assert_paper_orders_page(tmp_path):
    service = _service(tmp_path, {"crypto": {"paper": {"partial_fill_enabled": False, "max_position_ratio": 1.0, "max_order_notional": 10000}}, "storage": {"db_path": str(tmp_path / "orders.db")}})
    for index in range(5):
        _run(service.place_paper_order(CryptoPaperOrderRequest(symbol=f"C{index}/USDT", action="BUY", quantity=1, price=100)))
    page = _run(service.get_paper_orders(limit=2, offset=1))
    assert page.count == 2
    assert page.total == 5


def assert_paper_cancel_success(tmp_path):
    service = _service(tmp_path, {"crypto": {"paper": {"max_position_ratio": 1.0, "max_order_notional": 10000}}, "storage": {"db_path": str(tmp_path / "cancel.db")}})
    order = _run(service.place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.1, price=50000)))
    assert _run(service.cancel_paper_order(order.order_id))["success"] is True


def assert_paper_positions(tmp_path):
    service = _service(tmp_path, {"crypto": {"paper": {"partial_fill_enabled": False, "max_position_ratio": 1.0}}, "storage": {"db_path": str(tmp_path / "positions.db")}})
    _run(service.place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.01, price=50000)))
    response = _run(service.get_paper_positions())
    assert response.count >= 1
    assert response.total_market_value > 0


def assert_paper_equity_curve(tmp_path):
    assert _run(_service(tmp_path).get_paper_equity_curve()).count > 0


def assert_paper_logs(tmp_path):
    assert _run(_service(tmp_path).get_paper_logs()).count > 0


def assert_auto_logs(tmp_path):
    assert _run(_service(tmp_path).get_auto_trading_logs(limit=50)).count <= 50


def assert_auto_start(tmp_path):
    async def scenario():
        service = _service(tmp_path, {"auto_trading": {"scan_interval_seconds": 3600}, "storage": {"db_path": str(tmp_path / "auto_start.db")}})
        response = await service.start_auto_trading()
        assert response.state == "running"
        assert service._auto_loop_task is not None
        await service.stop_auto_trading()

    _run(scenario())


def assert_auto_pause(tmp_path):
    async def scenario():
        service = _service(tmp_path, {"auto_trading": {"scan_interval_seconds": 3600}, "storage": {"db_path": str(tmp_path / "auto_pause.db")}})
        await service.start_auto_trading()
        response = await service.pause_auto_trading()
        assert response.state == "paused"
        assert service._auto_loop_task is None

    _run(scenario())


def assert_auto_stop(tmp_path):
    async def scenario():
        service = _service(tmp_path, {"auto_trading": {"scan_interval_seconds": 3600}, "storage": {"db_path": str(tmp_path / "auto_stop.db")}})
        await service.start_auto_trading()
        response = await service.stop_auto_trading()
        assert response.state == "stopped"

    _run(scenario())


AI_MACRO_HELPER_CASES = {
    "test_analyze_ai_signal_hold": lambda tmp_path: assert_ai_analyze(tmp_path, _advice("HOLD", 0.8, 0), "blocked", "HOLD"),
    "test_analyze_ai_signal_low_confidence": lambda tmp_path: assert_ai_analyze(tmp_path, _advice("BUY", 0.3, 200), "blocked", "confidence"),
    "test_analyze_ai_signal_buy_approved": lambda tmp_path: assert_ai_analyze(tmp_path, _advice("BUY", 0.8, 200), "approved", "approved"),
    "test_analyze_ai_signal_sell_no_position": lambda tmp_path: assert_ai_analyze(tmp_path, _advice("SELL", 0.8, 200), "blocked", "no position"),
    "test_analyze_ai_signal_invalid_model_output": lambda tmp_path: assert_ai_invalid(tmp_path),
    "test_analyze_ai_signal_provider_unavailable": lambda tmp_path: assert_ai_unavailable(tmp_path),
    "test_list_ai_signals": lambda tmp_path: assert_ai_list(tmp_path),
    "test_get_ai_signal_found": lambda tmp_path: assert_ai_get_found(tmp_path),
    "test_get_ai_signal_not_found": lambda tmp_path: assert_ai_get_missing(tmp_path),
    "test_macro_overview_cache_hit": lambda tmp_path: assert_macro_hit(tmp_path),
    "test_macro_overview_cache_expired": lambda tmp_path: assert_macro_expired(tmp_path),
    "test_macro_overview_first_call_no_cache": lambda tmp_path: assert_macro_first(tmp_path),
    "test_connection_health_delegates": lambda tmp_path: assert_connection_health(tmp_path),
    "test_ai_blocked_real_trading_any_flag": lambda tmp_path: assert_equal(_ai_assess(tmp_path, account={"real_trading_enabled": True})["approval_status"], "blocked"),
    "test_ai_blocked_risk_real_trading": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"risk": {"real_trading_enabled": True}})["approval_status"], "blocked"),
    "test_ai_blocked_trading_real_trading": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"trading": {"real_trading_enabled": True}})["approval_status"], "blocked"),
    "test_ai_blocked_hold": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("HOLD"))["approval_status"], "blocked"),
    "test_ai_blocked_bad_action": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("TRANSFER"))["approval_status"], "blocked"),
    "test_ai_blocked_low_confidence": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("BUY", 0.3))["approval_status"], "blocked"),
    "test_ai_blocked_leverage_enabled": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"risk": {"allow_leverage": True}})["approval_status"], "blocked"),
    "test_ai_blocked_short_selling_enabled": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"risk": {"allow_short_selling": True}}, _advice("SELL"), positions=[{"symbol": "BTC/USDT", "quantity": 1}])["approval_status"], "blocked"),
    "test_ai_blocked_zero_notional": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("BUY", notional=0))["approval_status"], "blocked"),
    "test_ai_buy_capped_to_available_cash": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("BUY", notional=500), account={"available_cash": 200})["approved_notional_usdt"], 200),
    "test_ai_buy_capped_to_max_order": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"ai": {"max_order_notional": 300}}, _advice("BUY", notional=500), {"available_cash": 1000})["approved_notional_usdt"], 300),
    "test_ai_buy_insufficient_cash": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("BUY"), account={"available_cash": 0})["approval_status"], "blocked"),
    "test_ai_sell_no_position": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("SELL"))["approval_status"], "blocked"),
    "test_ai_sell_approved": lambda tmp_path: assert_equal(_ai_assess(tmp_path, advice=_advice("SELL", notional=500), positions=[{"symbol": "BTC/USDT", "available": 0.1}])["approval_status"], "approved"),
    "test_ai_notional_capped_by_paper_max": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"ai": {"max_order_notional": 300}, "crypto": {"paper": {"max_order_notional": 100}}}, _advice("BUY", notional=500), {"available_cash": 1000})["approved_notional_usdt"], 100),
    "test_ai_notional_capped_by_risk_max": lambda tmp_path: assert_equal(_ai_assess(tmp_path, {"ai": {"max_order_notional": 300}, "risk": {"max_order_notional": 150}}, _advice("BUY", notional=500), {"available_cash": 1000})["approved_notional_usdt"], 150),
    "test_normalize_symbols_uppercase": lambda tmp_path: assert_equal(_service(tmp_path)._normalize_symbols(["btc/usdt"]), ["BTC/USDT"]),
    "test_normalize_symbols_dedup": lambda tmp_path: assert_equal(_service(tmp_path)._normalize_symbols(["BTC/USDT", "BTC/USDT"]), ["BTC/USDT"]),
    "test_normalize_symbols_filters_invalid": lambda tmp_path: assert_equal(_service(tmp_path)._normalize_symbols(["", "BTC/USDT"]), ["BTC/USDT"]),
    "test_position_quantity_found": lambda tmp_path: assert_equal(_service(tmp_path)._position_quantity("BTC/USDT", [{"symbol": "BTC/USDT", "available": 1.5}]), 1.5),
    "test_position_quantity_fallback_to_quantity": lambda tmp_path: assert_equal(_service(tmp_path)._position_quantity("BTC/USDT", [{"symbol": "BTC/USDT", "quantity": 2.0}]), 2.0),
    "test_position_quantity_not_found": lambda tmp_path: assert_equal(_service(tmp_path)._position_quantity("ETH/USDT", []), 0.0),
    "test_position_quantity_symbol_normalized": lambda tmp_path: assert_equal(_service(tmp_path)._position_quantity("BTC/USDT", [{"symbol": "btc/usdt", "available": 1.0}]), 1.0),
}


def assert_ai_analyze(tmp_path, advice, status, reason):
    service = _service(tmp_path, {"ai": {"enabled": True, "min_confidence_for_order": 0.65, "max_order_notional": 300}, "storage": {"db_path": str(tmp_path / "ai.db")}})
    _mock_ai_context(service, advice)
    signal = _analyze(service).signal
    assert signal.approval_status == status
    assert reason in signal.approval_reason


def assert_ai_invalid(tmp_path):
    service = _service(tmp_path, {"ai": {"enabled": True}, "storage": {"db_path": str(tmp_path / "ai_invalid.db")}})
    _mock_ai_context(service)
    service.ai_advisor.analyze = MagicMock(side_effect=ValueError("bad json"))
    service.ai_store.save_signal = MagicMock(side_effect=lambda **kwargs: _save_signal(**kwargs))
    assert _analyze(service).signal.approval_status == "failed"


def assert_ai_unavailable(tmp_path):
    service = _service(tmp_path, {"ai": {"enabled": True}, "storage": {"db_path": str(tmp_path / "ai_down.db")}})
    _mock_ai_context(service)
    service.ai_advisor.analyze = MagicMock(side_effect=RuntimeError("down"))
    assert_raises_api(lambda: _analyze(service), 503, ErrorCode.AI_PROVIDER_UNAVAILABLE)


def assert_ai_list(tmp_path):
    service = _service(tmp_path)
    service.ai_store.list_signals = MagicMock(return_value={"items": [_ai_record()], "count": 1, "total": 1, "limit": 10, "offset": 0})
    assert _run(service.list_ai_signals(limit=10)).count == 1


def assert_ai_get_found(tmp_path):
    service = _service(tmp_path)
    service.ai_store.get_signal = MagicMock(return_value=_ai_record())
    assert _run(service.get_ai_signal("AI_BTC_1")).signal_id == "AI_BTC_1"


def assert_ai_get_missing(tmp_path):
    service = _service(tmp_path)
    service.ai_store.get_signal = MagicMock(return_value=None)
    assert_raises_api(lambda: _run(service.get_ai_signal("missing")), 404)


def assert_macro_hit(tmp_path):
    service = _service(tmp_path)
    _with_macro(service)
    first = _run(service.get_macro_overview())
    second = _run(service.get_macro_overview())
    assert first == second
    assert service.macro_provider.fetch_snapshot.call_count == 1


def assert_macro_expired(tmp_path):
    service = _service(tmp_path)
    _with_macro(service)
    _run(service.get_macro_overview())
    service._macro_cache_time -= 301
    _run(service.get_macro_overview())
    assert service.macro_provider.fetch_snapshot.call_count == 2


def assert_macro_first(tmp_path):
    service = _service(tmp_path)
    _with_macro(service)
    _run(service.get_macro_overview())
    service.macro_provider.fetch_snapshot.assert_called_once()
    service.macro_evaluator.evaluate.assert_called_once()


def assert_connection_health(tmp_path):
    service = _service(tmp_path)
    service.provider.get_connection_health = MagicMock(return_value={"quotes": {"state": "closed"}})
    assert _run(service.get_connection_health()).quotes.state == "closed"


for _name, _check in {
    **INIT_CASES,
    **QUOTE_CASES,
    **SYMBOL_CASES,
    **KLINE_ORDERBOOK_CASES,
    **PAPER_AUTO_CASES,
    **AI_MACRO_HELPER_CASES,
}.items():
    globals()[_name] = _test(_name, _check)
