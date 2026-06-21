import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_crypto_service
from api.error_codes import ApiError, ErrorCode
from api.main import app
from api.models.request import AiChatRequest
from api.models.response import CryptoKLineResponse, CryptoKLinesResponse, CryptoQuoteResponse, CryptoQuotesResponse
from api.services.crypto_service import CryptoService
from core.ai_chat_assistant import AiChatAssistant


def _quote(symbol="BTC/USDT"):
    return {
        "symbol": symbol,
        "price": 50000.0,
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
        "source": "unit",
    }


def _kline(symbol="BTC/USDT", close=50000.0):
    return {
        "symbol": symbol,
        "period": "1h",
        "start_time": "2026-05-21T00:00:00Z",
        "end_time": "2026-05-21T00:59:59Z",
        "open": close - 100,
        "high": close + 100,
        "low": close - 200,
        "close": close,
        "volume": 10.0,
        "amount": close * 10.0,
        "count": 1,
    }


def _service(tmp_path, *, ai_enabled=True):
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
                    "real_trading_enabled": False,
                },
            },
            "risk": {
                "max_order_notional": 300,
                "allow_short_selling": False,
                "allow_leverage": False,
                "real_trading_enabled": False,
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
            "storage": {"db_path": str(tmp_path / "ai_chat.db")},
        }
    )
    service.get_quotes = AsyncMock(
        return_value=CryptoQuotesResponse(items=[CryptoQuoteResponse(**_quote())], count=1, source="unit")
    )
    service.get_klines = AsyncMock(
        return_value=CryptoKLinesResponse(
            symbol="BTC/USDT",
            period="1h",
            items=[CryptoKLineResponse(**_kline(close=50000 + index)) for index in range(30)],
            count=30,
        )
    )
    service.get_macro_overview = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: {"gate": {"state": "ALLOW_FULL"}}))
    service.paper_broker.get_account_info = MagicMock(return_value={"cash": 1000, "available_cash": 1000, "equity": 1000})
    service.paper_broker.get_positions = MagicMock(return_value=[{"symbol": "BTC/USDT", "quantity": 0.01, "available": 0.01}])
    service.paper_broker.get_orders = MagicMock(return_value={"items": [{"order_id": "PAPER_1", "symbol": "BTC/USDT"}]})
    service.paper_broker.place_order = MagicMock()
    service.testnet_executor.place_order = MagicMock()
    return service


def _run(awaitable):
    return asyncio.run(awaitable)


async def _collect_async(iterator):
    return [item async for item in iterator]


def test_ai_chat_persists_session_messages_and_context(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "这是模拟研究建议，不会替你下单。"})

    response = _run(
        service.chat_ai_assistant(
            AiChatRequest(symbol="BTC/USDT", period="1h", limit=60, message="帮我分析 BTC 当前风险")
        )
    )

    assert response.session.session_id.startswith("AICHAT_")
    assert response.session.message_count == 2
    assert response.user_message.role == "user"
    assert response.assistant_message.role == "assistant"
    assert response.assistant_message.context_summary["symbol"] == "BTC/USDT"
    assert response.assistant_message.context_summary["real_order_allowed_by_ai"] is False
    service.paper_broker.place_order.assert_not_called()
    service.testnet_executor.place_order.assert_not_called()

    detail = _run(service.get_ai_chat_session(response.session.session_id))
    assert [message.role for message in detail.messages] == ["user", "assistant"]
    listed = _run(service.list_ai_chat_sessions())
    assert listed.total == 1


def test_ai_chat_can_continue_and_delete_session(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "第一条回复"})
    first = _run(service.chat_ai_assistant(AiChatRequest(message="第一条", symbol="BTC/USDT")))

    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "第二条回复"})
    second = _run(
        service.chat_ai_assistant(
            AiChatRequest(session_id=first.session.session_id, message="继续分析", symbol="BTC/USDT")
        )
    )

    assert second.session.session_id == first.session.session_id
    assert second.session.message_count == 4
    call_kwargs = service.ai_chat_assistant.chat.call_args.kwargs
    assert len(call_kwargs["recent_messages"]) == 2

    deleted = _run(service.delete_ai_chat_session(first.session.session_id))
    assert deleted["success"] is True
    with pytest.raises(ApiError):
        _run(service.get_ai_chat_session(first.session.session_id))


def test_ai_chat_passes_selected_model_to_assistant(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "deepseek-v4-pro", "content": "Pro reply"})

    response = _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="Analyze BTC risk",
                symbol="BTC/USDT",
                model="deepseek-v4-pro",
            )
        )
    )

    assert service.ai_chat_assistant.chat.call_args.kwargs["model"] == "deepseek-v4-pro"
    assert response.assistant_message.model == "deepseek-v4-pro"


def test_ai_chat_provider_unavailable_when_disabled(tmp_path):
    service = _service(tmp_path, ai_enabled=False)

    with pytest.raises(ApiError) as exc_info:
        _run(service.chat_ai_assistant(AiChatRequest(message="分析一下", symbol="BTC/USDT")))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert _run(service.list_ai_chat_sessions()).total == 0


def test_deepseek_chat_provider_uses_chat_completions(monkeypatch):
    captured = {}

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="这是 DeepSeek 模拟研究建议。"))]
            )

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")

    assistant = AiChatAssistant(
        {
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "fallback_model": "deepseek-v4-flash",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
        }
    )
    result = assistant.chat(message="分析 BTC", context_summary={"symbol": "BTC/USDT"})

    assert result == {"model": "deepseek-v4-flash", "content": "这是 DeepSeek 模拟研究建议。"}
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["request"]["model"] == "deepseek-v4-flash"


def test_ai_chat_without_context_skips_market_fetch_and_hides_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "仅基于问题给出模拟研究建议。"})

    result = _run(
        service.chat_ai_assistant(
            AiChatRequest(message="不用上下文，解释一下回撤", symbol="BTC/USDT", include_context=False)
        )
    )

    service.get_quotes.assert_not_called()
    service.get_klines.assert_not_called()
    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    serialized_context = str(context)
    assert "sk-test-secret" not in serialized_context
    assert "OPENAI_API_KEY" not in serialized_context
    assert context["ai_limits"]["real_trading_allowed"] is False
    assert result.assistant_message.content.startswith("仅基于问题")


def test_ai_chat_without_market_context_still_includes_project_copilot_knowledge(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "我是项目副驾驶，可以解释每个模块。"})

    result = _run(
        service.chat_ai_assistant(
            AiChatRequest(message="这个项目怎么用？", symbol="BTC/USDT", include_context=False)
        )
    )

    service.get_quotes.assert_not_called()
    service.get_klines.assert_not_called()
    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["assistant_scope"]["role"] == "HuuQuantAI 项目副驾驶"
    assert "正常聊天" in context["assistant_scope"]["can_help_with"]
    module_ids = {item["id"] for item in context["project_modules"]}
    assert {"dashboard", "market", "manual_trade", "risk", "settings"}.issubset(module_ids)
    assert context["safety_boundaries"]["real_trading_allowed"] is False
    assert context["safety_boundaries"]["can_place_orders"] is False
    assert "这个项目怎么用？" in context["suggested_questions"]
    assert result.context_summary["current_workspace"]["symbol"] == "BTC/USDT"


def test_ai_chat_with_context_adds_project_workspace_and_runtime_summary(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "当前模拟账户现金充足。"})

    _run(service.chat_ai_assistant(AiChatRequest(message="帮我解释当前账户和风控", symbol="BTC/USDT")))

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["current_workspace"]["context_mode"] == "project_and_market"
    assert context["available_capabilities"]["paper_trading"] is True
    assert context["available_capabilities"]["project_usage_help"] is True
    assert context["runtime_summary"]["account"]["cash"] == 1000
    assert context["runtime_summary"]["positions_count"] == 1
    assert context["runtime_summary"]["recent_orders_count"] == 1
    assert context["real_order_allowed_by_ai"] is False
    service.paper_broker.place_order.assert_not_called()
    service.testnet_executor.place_order.assert_not_called()


def test_ai_chat_current_route_adds_active_module_guide(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "风控中心会解释阻断原因。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="这个是什么意思？",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/risk",
                current_view_title="风控中心",
                visible_context={"risk_state": "blocked", "reason": "max_order_notional"},
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["current_workspace"]["current_route"] == "/risk"
    assert context["current_workspace"]["current_module"] == "risk"
    assert context["current_workspace"]["current_view_title"] == "风控中心"
    assert context["current_workspace"]["visible_context"]["risk_state"] == "blocked"
    assert context["active_module_guide"]["id"] == "risk"
    assert context["active_module_guide"]["name"] == "风控中心"
    assert "这个风控阻断是什么意思" in context["route_suggested_questions"]


def test_ai_chat_current_module_overrides_route_and_sanitizes_visible_context(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "自动交易页面会解释扫描链路。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="为什么没下单？",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/unknown",
                current_module="auto_trade",
                visible_context={
                    "status": "paused",
                    "nested": {"orders": [1, 2, 3], "secret_like": "safe-public-state"},
                    "large_text": "x" * 2000,
                },
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["current_workspace"]["current_module"] == "auto_trade"
    assert context["active_module_guide"]["id"] == "auto_trade"
    assert "为什么自动交易没有下单" in context["route_suggested_questions"]
    assert len(context["current_workspace"]["visible_context"]["large_text"]) <= 520


def test_ai_chat_strategy_guide_mode_returns_backtest_operation_guide(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "按步骤运行策略回测。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="我想跑一次策略回测",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/strategy",
                current_module="strategy",
                guide_mode=True,
                user_goal="跑一次策略回测",
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["guide_mode"] is True
    assert context["active_operation_guide"]["id"] == "strategy_backtest"
    assert context["active_operation_guide"]["module"] == "strategy"
    assert len(context["active_operation_guide"]["steps"]) >= 3
    assert "manual_click" in context["allowed_user_actions"]
    assert "place_order" in context["forbidden_ai_actions"]


def test_ai_chat_auto_guide_mode_selects_no_order_diagnostics(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "先检查扫描和风控。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="为什么自动交易没下单？",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/auto",
                guide_mode=True,
                user_goal="排查为什么没下单",
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["active_operation_guide"]["id"] == "auto_no_order_diagnostics"
    assert context["active_operation_guide"]["module"] == "auto_trade"
    assert "auto_no_order_diagnostics" in {item["id"] for item in context["operation_guides"]}


def test_ai_chat_risk_guide_mode_selects_risk_block_explanation(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "先看阻断原因。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="这个风控阻断是什么意思？",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/risk",
                guide_mode=True,
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert context["active_operation_guide"]["id"] == "risk_block_explanation"
    assert context["active_operation_guide"]["module"] == "risk"
    assert context["active_operation_guide"]["safety_notice"]


def test_ai_chat_context_builds_safe_action_cards_and_workspace_state(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "打开策略中心并查看回测。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="跑一次策略回测",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/strategy",
                current_module="strategy",
                guide_mode=True,
                user_goal="跑一次策略回测",
                visible_context={
                    "api_key": "DEEPSEEK_SECRET_SHOULD_NOT_LEAK",
                    "token": "TOKEN_SHOULD_NOT_LEAK",
                    "public_state": "strategy-page",
                },
            )
        )
    )

    context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    cards = context["action_cards"]
    assert cards
    assert {card["action_type"] for card in cards} <= {"navigate", "inspect", "explain"}
    assert {"place_order", "cancel_order", "enable_real_trading", "change_config", "call_trade_api"}.isdisjoint(
        {card["action_type"] for card in cards}
    )
    assert any(card["target_route"] == "/backtest" for card in cards)
    assert context["workspace_state"]["current_route"] == "/strategy"
    assert context["workspace_state"]["real_trading_status"] == "disabled"
    assert context["decision_chain_summary"]["stages"] == [
        "market_data",
        "strategy_signal",
        "confidence",
        "macro_gate",
        "risk_approval",
        "cash_position",
        "paper_order",
    ]
    serialized = str(context)
    assert "DEEPSEEK_SECRET_SHOULD_NOT_LEAK" not in serialized
    assert "TOKEN_SHOULD_NOT_LEAK" not in serialized
    assert "[redacted]" in serialized


def test_ai_chat_auto_and_risk_routes_return_relevant_action_cards(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "检查风控和审计。"})

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="为什么没下单",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/auto",
                guide_mode=True,
                user_goal="排查为什么没下单",
            )
        )
    )
    auto_context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert {card["target_route"] for card in auto_context["action_cards"]} >= {"/auto", "/risk", "/audit"}
    assert auto_context["risk_block_summary"]["real_trading_enabled"] is False

    _run(
        service.chat_ai_assistant(
            AiChatRequest(
                message="风控阻断是什么意思",
                symbol="BTC/USDT",
                include_context=False,
                current_route="/risk",
                guide_mode=True,
                user_goal="查看风控阻断原因",
            )
        )
    )
    risk_context = service.ai_chat_assistant.chat.call_args.kwargs["context_summary"]
    assert {card["target_route"] for card in risk_context["action_cards"]} >= {"/risk", "/audit"}
    assert risk_context["module_usage_guide"]["id"] == "risk"


def test_ai_chat_api_routes(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.chat = MagicMock(return_value={"model": "gpt-5.2", "content": "模拟研究建议。"})
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: service

    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-token"}
            chatted = client.post(
                "/api/v1/crypto/ai/chat",
                headers=headers,
                json={"symbol": "BTC/USDT", "period": "1h", "limit": 60, "message": "BTC 怎么看？"},
            )
            assert chatted.status_code == 200
            session_id = chatted.json()["session"]["session_id"]

            listed = client.get("/api/v1/crypto/ai/chat/sessions", headers=headers)
            assert listed.status_code == 200
            assert listed.json()["total"] == 1

            detail = client.get(f"/api/v1/crypto/ai/chat/sessions/{session_id}", headers=headers)
            assert detail.status_code == 200
            assert len(detail.json()["messages"]) == 2

            deleted = client.delete(f"/api/v1/crypto/ai/chat/sessions/{session_id}", headers=headers)
            assert deleted.status_code == 200
            assert deleted.json()["success"] is True
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()


def test_deepseek_stream_chat_emits_start_deltas_and_done(monkeypatch):
    captured = {}

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return iter(
                [
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="risk "))]),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="looks contained"))]),
                ]
            )

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url=None):
            self.chat = SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")

    assistant = AiChatAssistant(
        {
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "fallback_model": "deepseek-v4-flash",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
        }
    )

    events = list(assistant.stream_chat(message="Analyze risk", context_summary={"symbol": "BTC/USDT"}))

    assert captured["request"]["stream"] is True
    assert [event["event"] for event in events] == ["start", "delta", "delta", "done"]
    assert events[1]["content"] == "risk "
    assert events[-1] == {
        "event": "done",
        "model": "deepseek-v4-flash",
        "content": "risk looks contained",
    }


def test_ai_chat_stream_service_persists_only_completed_exchange(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.stream_chat = MagicMock(
        return_value=iter(
            [
                {"event": "start", "model": "gpt-5.2"},
                {"event": "delta", "model": "gpt-5.2", "content": "paper "},
                {"event": "delta", "model": "gpt-5.2", "content": "research"},
                {"event": "done", "model": "gpt-5.2", "content": "paper research"},
            ]
        )
    )

    events = _run(
        _collect_async(
            service.stream_ai_assistant(
                AiChatRequest(symbol="BTC/USDT", period="1h", limit=60, message="Explain the current risk")
            )
        )
    )

    assert [event["event"] for event in events] == ["start", "delta", "delta", "done"]
    assert events[-1]["data"]["assistant_message"]["content"] == "paper research"
    assert _run(service.list_ai_chat_sessions()).total == 1
    service.paper_broker.place_order.assert_not_called()
    service.testnet_executor.place_order.assert_not_called()


def test_ai_chat_stream_api_uses_sse_event_contract(tmp_path):
    service = _service(tmp_path)
    service.ai_chat_assistant.stream_chat = MagicMock(
        return_value=iter(
            [
                {"event": "start", "model": "gpt-5.2"},
                {"event": "delta", "model": "gpt-5.2", "content": "hello"},
                {"event": "done", "model": "gpt-5.2", "content": "hello"},
            ]
        )
    )
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "tester"}
    app.dependency_overrides[get_crypto_service] = lambda: service

    try:
        with TestClient(app) as client:
            with client.stream(
                "POST",
                "/api/v1/crypto/ai/chat/stream",
                headers={"Authorization": "Bearer test-token"},
                json={"symbol": "BTC/USDT", "period": "1h", "limit": 60, "message": "Hello"},
            ) as response:
                body = "".join(response.iter_text())

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: start" in body
        assert "event: delta" in body
        assert "event: done" in body
        done_data = next(
            json.loads(line.removeprefix("data: "))
            for block in body.split("\n\n")
            if block.startswith("event: done")
            for line in block.splitlines()
            if line.startswith("data: ")
        )
        assert done_data["assistant_message"]["content"] == "hello"
    finally:
        app.dependency_overrides.clear()
        get_crypto_service.cache_clear()


def test_ai_chat_stream_error_does_not_persist_partial_exchange(tmp_path):
    service = _service(tmp_path)

    def broken_stream(**_kwargs):
        yield {"event": "start", "model": "gpt-5.2"}
        yield {"event": "delta", "model": "gpt-5.2", "content": "partial"}
        raise RuntimeError("provider disconnected")

    service.ai_chat_assistant.stream_chat = broken_stream
    events = _run(
        _collect_async(
            service.stream_ai_assistant(
                AiChatRequest(symbol="BTC/USDT", period="1h", message="Explain risk")
            )
        )
    )

    assert [event["event"] for event in events] == ["start", "delta", "error"]
    assert events[-1]["data"]["retryable"] is True
    assert _run(service.list_ai_chat_sessions()).total == 0
    service.paper_broker.place_order.assert_not_called()
    service.testnet_executor.place_order.assert_not_called()
