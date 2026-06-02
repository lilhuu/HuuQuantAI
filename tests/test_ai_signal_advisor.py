import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.error_codes import ApiError, ErrorCode
from api.main import app
from api.models.request import AiSignalAnalyzeRequest
from api.services.crypto_service import CryptoService
from core.crypto_market_data_provider import CryptoMarketDataProvider


def _fake_quotes(self, symbols):
    return [
        {
            "symbol": str(symbol).replace("BTCUSDT", "BTC/USDT").replace("ETHUSDT", "ETH/USDT"),
            "price": 50000.0 if "BTC" in str(symbol) else 3000.0,
            "open": 49500.0,
            "high": 50500.0,
            "low": 49000.0,
            "volume": 123.0,
            "amount": 6150000.0,
            "change": 0.01,
            "change_amount": 500.0,
            "bid": 49999.0,
            "ask": 50001.0,
            "timestamp": "2026-05-21T00:00:00Z",
            "source": "binance",
        }
        for symbol in symbols
    ]


def _fake_ohlcv(self, symbol, timeframe="1h", limit=200):
    normalized = "BTC/USDT" if "BTC" in str(symbol) else "ETH/USDT"
    return [
        {
            "symbol": normalized,
            "period": timeframe,
            "start_time": f"2026-05-21T{i:02d}:00:00Z",
            "end_time": f"2026-05-21T{i:02d}:59:59Z",
            "open": 49000.0 + i,
            "high": 50100.0 + i,
            "low": 48900.0 + i,
            "close": 50000.0 + i,
            "volume": 10.0 + i,
            "amount": (50000.0 + i) * (10.0 + i),
            "count": 1,
        }
        for i in range(max(30, min(int(limit or 120), 120)))
    ]


def _make_service(tmp_path, *, ai_enabled=True, real_trading_enabled=False):
    service = CryptoService(
        {
            "crypto": {
                "exchange": "binance",
                "default_quote_currency": "USDT",
                "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                "paper": {
                    "initial_cash": 10000,
                    "max_order_notional": 2000,
                    "max_position_ratio": 1.0,
                    "partial_fill_enabled": False,
                    "real_trading_enabled": real_trading_enabled,
                },
            },
            "risk": {
                "max_order_notional": 300,
                "allow_short_selling": False,
                "allow_leverage": False,
                "real_trading_enabled": real_trading_enabled,
            },
            "ai": {
                "enabled": ai_enabled,
                "provider": "openai",
                "model": "gpt-5.2",
                "fallback_model": "gpt-5-mini",
                "api_key_env": "OPENAI_API_KEY",
                "mode": "advisory",
                "manual_confirm_required": True,
                "auto_paper_order_enabled": False,
                "min_confidence_for_order": 0.65,
                "max_context_candles": 120,
                "max_order_notional": 300,
            },
            "storage": {"db_path": str(tmp_path / "ai_signal_state.db")},
        }
    )

    async def fake_macro():
        return SimpleNamespace(model_dump=lambda: {"source": "test", "risk_level": "neutral"})

    service.get_macro_overview = fake_macro
    return service


def _advice(action="BUY", confidence=0.82, suggested_notional=500.0):
    return {
        "symbol": "BTC/USDT",
        "action": action,
        "confidence": confidence,
        "suggested_notional_usdt": suggested_notional,
        "max_loss_usdt": 25.0,
        "time_horizon": "1h-4h",
        "reason": "Momentum is positive but risk remains bounded.",
        "risk_notes": ["Volatility can expand quickly."],
        "invalid_if": ["Price breaks below the recent support range."],
        "model": "gpt-5.2",
    }


def test_ai_signal_buy_is_saved_and_manual_paper_order_is_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", _fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", _fake_ohlcv)
    service = _make_service(tmp_path)
    service.ai_advisor.analyze = lambda context: _advice(suggested_notional=500)

    response = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))
    assert response.signal.action == "BUY"
    assert response.signal.approval_status == "approved"
    assert response.signal.approved_notional_usdt == 300

    order_response = asyncio.run(service.create_ai_signal_paper_order(response.signal.signal_id))
    assert order_response.success is True
    assert order_response.order is not None
    assert order_response.order.strategy.startswith("ai:")
    assert order_response.signal.linked_order_id == order_response.order.order_id
    assert service.paper_broker.get_positions()[0]["symbol"] == "BTC/USDT"


def test_ai_signal_hold_and_low_confidence_cannot_generate_orders(monkeypatch, tmp_path):
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", _fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", _fake_ohlcv)
    service = _make_service(tmp_path)

    service.ai_advisor.analyze = lambda context: _advice(action="HOLD", confidence=0.9, suggested_notional=300)
    hold = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))
    assert hold.signal.approval_status == "blocked"
    assert "HOLD" in hold.signal.approval_reason
    rejected_hold = asyncio.run(service.create_ai_signal_paper_order(hold.signal.signal_id))
    assert rejected_hold.success is False

    service.ai_advisor.analyze = lambda context: _advice(action="BUY", confidence=0.4, suggested_notional=300)
    low = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))
    assert low.signal.approval_status == "blocked"
    assert "confidence below threshold" in low.signal.approval_reason


def test_ai_signal_sell_without_position_and_real_switch_are_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", _fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", _fake_ohlcv)
    service = _make_service(tmp_path)
    service.ai_advisor.analyze = lambda context: _advice(action="SELL", confidence=0.85, suggested_notional=300)

    sell = asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))
    assert sell.signal.approval_status == "blocked"
    assert "short selling disabled" in sell.signal.approval_reason

    live_service = _make_service(tmp_path / "live", real_trading_enabled=True)
    live_service.ai_advisor.analyze = lambda context: _advice(action="BUY", confidence=0.85, suggested_notional=300)
    live = asyncio.run(live_service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))
    assert live.signal.approval_status == "blocked"
    assert "real trading" in live.signal.approval_reason


def test_ai_provider_unavailable_when_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", _fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", _fake_ohlcv)
    service = _make_service(tmp_path)

    with pytest.raises(ApiError) as exc_info:
        asyncio.run(service.analyze_ai_signal(AiSignalAnalyzeRequest(symbol="BTC/USDT", period="1h", limit=60)))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == ErrorCode.AI_PROVIDER_UNAVAILABLE


def test_ai_signal_api_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_quotes", _fake_quotes)
    monkeypatch.setattr(CryptoMarketDataProvider, "fetch_ohlcv", _fake_ohlcv)
    service = _make_service(tmp_path)
    service.ai_advisor.analyze = lambda context: _advice(action="BUY", confidence=0.82, suggested_notional=250)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: service

    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-token"}
            analyzed = client.post(
                "/api/v1/crypto/ai/analyze",
                headers=headers,
                json={"symbol": "BTC/USDT", "period": "1h", "limit": 60},
            )
            assert analyzed.status_code == 200
            signal_id = analyzed.json()["signal"]["signal_id"]

            listed = client.get("/api/v1/crypto/ai/signals", headers=headers)
            assert listed.status_code == 200
            assert listed.json()["total"] == 1

            ordered = client.post(f"/api/v1/crypto/ai/signals/{signal_id}/paper-order", headers=headers)
            assert ordered.status_code == 200
            assert ordered.json()["success"] is True
            assert ordered.json()["order"]["strategy"].startswith("ai:")
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()
