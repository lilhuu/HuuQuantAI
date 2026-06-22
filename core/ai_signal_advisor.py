"""AI-assisted crypto signal advisor.

The advisor is advisory-only. It never places orders and never talks to
Binance Testnet or mainnet. Order conversion is handled by CryptoService after
local validation and user confirmation.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.crypto_market_data_provider import normalize_crypto_symbol
from core.sqlite_utils import configure_sqlite_connection


AI_SIGNAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "symbol",
        "action",
        "confidence",
        "suggested_notional_usdt",
        "max_loss_usdt",
        "time_horizon",
        "reason",
        "risk_notes",
        "invalid_if",
    ],
    "properties": {
        "symbol": {"type": "string"},
        "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "suggested_notional_usdt": {"type": "number", "minimum": 0},
        "max_loss_usdt": {"type": "number", "minimum": 0},
        "time_horizon": {"type": "string"},
        "reason": {"type": "string"},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
        "invalid_if": {"type": "array", "items": {"type": "string"}},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))


def parse_ai_response_payload(output_text: str, *, provider_label: str = "AI") -> dict[str, Any]:
    """Parse provider output that may contain a raw JSON object or a fenced JSON block."""
    text = str(output_text or "").strip()
    if not text:
        return fallback_hold_advice(reason=f"{provider_label} 返回为空，已按安全规则转为 HOLD。")

    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates = fenced + candidates
    object_text = _extract_first_json_object(text)
    if object_text:
        candidates.append(object_text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    excerpt = text.replace("\n", " ")[:180]
    return fallback_hold_advice(
        reason=f"{provider_label} 没有返回可解析的 JSON 交易信号，已按安全规则转为 HOLD。原始摘要：{excerpt}"
    )


def fallback_hold_advice(*, symbol: str = "", reason: str = "AI 返回格式不完整，已按安全规则转为 HOLD。") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "action": "HOLD",
        "confidence": 0.0,
        "suggested_notional_usdt": 0.0,
        "max_loss_usdt": 0.0,
        "time_horizon": "",
        "reason": reason,
        "risk_notes": ["AI 输出未完全符合本地结构化格式，系统未生成可交易建议。"],
        "invalid_if": ["重新分析前保持观望。"],
    }


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


@dataclass
class AiAdvisorConfig:
    enabled: bool = False
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    fallback_model: str = "deepseek-v4-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com"
    mode: str = "advisory"
    manual_confirm_required: bool = True
    auto_paper_order_enabled: bool = False
    min_confidence_for_order: float = 0.65
    max_context_candles: int = 120
    max_order_notional: float = 300.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AiAdvisorConfig":
        data = dict(payload or {})
        return cls(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider") or "deepseek").lower(),
            model=str(data.get("model") or "deepseek-v4-flash"),
            fallback_model=str(data.get("fallback_model") or "deepseek-v4-flash"),
            api_key_env=str(data.get("api_key_env") or "DEEPSEEK_API_KEY"),
            base_url=str(data.get("base_url") or "https://api.deepseek.com"),
            mode=str(data.get("mode") or "advisory"),
            manual_confirm_required=bool(data.get("manual_confirm_required", True)),
            auto_paper_order_enabled=bool(data.get("auto_paper_order_enabled", False)),
            min_confidence_for_order=max(0.0, min(float(data.get("min_confidence_for_order", 0.65) or 0.65), 1.0)),
            max_context_candles=max(30, min(int(data.get("max_context_candles", 120) or 120), 500)),
            max_order_notional=max(1.0, float(data.get("max_order_notional", 300) or 300)),
        )


class AiSignalContextBuilder:
    """Build compact AI input from market/account state."""

    @staticmethod
    def build(
        *,
        symbol: str,
        period: str,
        quote: dict[str, Any],
        klines: list[dict[str, Any]],
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        recent_orders: list[dict[str, Any]],
        risk_config: dict[str, Any],
        ai_config: AiAdvisorConfig,
        macro: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candles = klines[-ai_config.max_context_candles :]
        closes = [float(item.get("close", 0) or 0) for item in candles]
        latest_close = closes[-1] if closes else float(quote.get("price", 0) or 0)
        first_close = closes[0] if closes else latest_close
        high = max([float(item.get("high", 0) or 0) for item in candles] or [latest_close])
        low = min([float(item.get("low", 0) or 0) for item in candles] or [latest_close])
        return {
            "symbol": normalize_crypto_symbol(symbol),
            "period": str(period or "1h"),
            "generated_at": utc_now(),
            "market": {
                "quote": quote,
                "candles": candles,
                "summary": {
                    "candle_count": len(candles),
                    "latest_close": latest_close,
                    "return_pct": ((latest_close - first_close) / first_close * 100) if first_close else 0.0,
                    "range_high": high,
                    "range_low": low,
                    "range_pct": ((high - low) / latest_close * 100) if latest_close else 0.0,
                },
            },
            "account": {
                "cash": float(account.get("cash", 0) or 0),
                "available_cash": float(account.get("available_cash", account.get("cash", 0)) or 0),
                "equity": float(account.get("equity", 0) or 0),
                "market_value": float(account.get("market_value", 0) or 0),
                "real_trading_enabled": bool(account.get("real_trading_enabled", False)),
            },
            "positions": positions,
            "recent_orders": recent_orders[-20:],
            "risk": risk_config,
            "ai_limits": {
                "mode": ai_config.mode,
                "manual_confirm_required": True,
                "auto_paper_order_enabled": False,
                "min_confidence_for_order": ai_config.min_confidence_for_order,
                "max_order_notional": ai_config.max_order_notional,
                "real_trading_allowed": False,
                "short_selling_allowed": False,
                "leverage_allowed": False,
            },
            "macro": macro or {},
        }

    @staticmethod
    def summarize(context: dict[str, Any]) -> dict[str, Any]:
        market = context.get("market", {}) or {}
        account = context.get("account", {}) or {}
        return {
            "symbol": context.get("symbol", ""),
            "period": context.get("period", ""),
            "generated_at": context.get("generated_at", ""),
            "market_summary": market.get("summary", {}),
            "quote": market.get("quote", {}),
            "account": account,
            "position_count": len(context.get("positions", []) or []),
            "recent_order_count": len(context.get("recent_orders", []) or []),
            "risk": context.get("risk", {}),
            "ai_limits": context.get("ai_limits", {}),
            "macro": context.get("macro", {}),
            "execution_mode": context.get("execution_mode", "advisory"),
            "strategy_candidate": context.get("strategy_candidate", {}),
        }


class AiSignalAdvisor:
    """Provider-backed structured crypto signal advisor."""

    def __init__(self, config: dict[str, Any] | AiAdvisorConfig | None = None) -> None:
        self.config = config if isinstance(config, AiAdvisorConfig) else AiAdvisorConfig.from_dict(config)

    def analyze(
        self,
        context: dict[str, Any],
        *,
        selected_model: str | None = None,
        fallback_model: str | None = None,
        execution_mode: str = "advisory",
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("AI advisor is disabled in config")
        if self.config.provider not in {"openai", "deepseek"}:
            raise RuntimeError(f"unsupported AI provider: {self.config.provider}")
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"missing {self._provider_label()} API key env: {self.config.api_key_env}")

        last_error: Exception | None = None
        for model in self._candidate_models(selected_model, fallback_model):
            if not model:
                continue
            try:
                payload = self._call_provider(
                    api_key=api_key,
                    model=model,
                    context=context,
                    execution_mode=execution_mode,
                )
                validated = validate_ai_advice(payload, expected_symbol=str(context.get("symbol") or ""))
                validated["model"] = model
                return validated
            except Exception as exc:  # pragma: no cover - exercised through service tests with monkeypatch.
                last_error = exc
                if model == self.config.fallback_model:
                    break
        raise RuntimeError(f"{self._provider_label()} AI signal request failed: {last_error}")

    def _candidate_models(self, selected_model: str | None = None, fallback_model: str | None = None) -> list[str]:
        candidates: list[str] = []
        for model in [selected_model or self.config.model, fallback_model or self.config.fallback_model]:
            model_text = str(model or "").strip()
            if model_text and model_text not in candidates:
                candidates.append(model_text)
        return candidates

    def _provider_label(self) -> str:
        return "DeepSeek" if self.config.provider == "deepseek" else "OpenAI"

    def _call_provider(
        self,
        *,
        api_key: str,
        model: str,
        context: dict[str, Any],
        execution_mode: str,
    ) -> dict[str, Any]:
        if self.config.provider == "deepseek":
            return self._call_deepseek(api_key=api_key, model=model, context=context, execution_mode=execution_mode)
        return self._call_openai(api_key=api_key, model=model, context=context, execution_mode=execution_mode)

    def _call_openai(self, *, api_key: str, model: str, context: dict[str, Any], execution_mode: str) -> dict[str, Any]:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=self._system_prompt(execution_mode),
            input=safe_json(context),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "crypto_ai_signal_advice",
                    "schema": AI_SIGNAL_SCHEMA,
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", "") or self._extract_output_text(response)
        if not output_text:
            raise ValueError("OpenAI response did not include output_text")
        return json.loads(output_text)

    def _call_deepseek(self, *, api_key: str, model: str, context: dict[str, Any], execution_mode: str) -> dict[str, Any]:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=self.config.base_url or "https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": self._system_prompt(execution_mode)},
                {"role": "user", "content": safe_json(context)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        choices = getattr(response, "choices", []) or []
        if not choices:
            raise ValueError("DeepSeek response did not include choices")
        message = getattr(choices[0], "message", None)
        output_text = getattr(message, "content", "") if message else ""
        if not output_text:
            raise ValueError("DeepSeek response did not include message content")
        return parse_ai_response_payload(output_text, provider_label="DeepSeek")

    def _system_prompt(self, execution_mode: str = "advisory") -> str:
        execution_rule = (
            "A local risk engine may convert an approved signal into a PaperBroker simulation order without manual confirmation. "
            "You cannot bypass its limits, call an exchange, or enable real trading. "
            if execution_mode == "auto_paper"
            else "The user must manually confirm any paper order; you cannot place orders. "
        )
        return (
            "You are an advisory-only crypto risk analyst for a local paper-trading system. "
            "Return only one valid JSON object that matches the schema. Do not wrap it in Markdown. "
            "Required keys: symbol, action, confidence, suggested_notional_usdt, max_loss_usdt, "
            "time_horizon, reason, risk_notes, invalid_if. "
            "Use action HOLD, confidence 0, and suggested_notional_usdt 0 when uncertain. "
            "Do not promise profits. "
            "Never recommend leverage, short selling, mainnet trading, or bypassing risk checks. "
            "Prefer HOLD when the evidence is weak. Include concrete risk notes and invalidation conditions. "
            + execution_rule
        )

    def _extract_output_text(self, response: Any) -> str:
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()


class AiSignalStore:
    """SQLite store for AI signal advice and local approval state."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._setup()

    def save_signal(
        self,
        *,
        symbol: str,
        period: str,
        model: str,
        request_summary: dict[str, Any],
        response: dict[str, Any],
        approval_status: str,
        approval_reason: str,
        approved_notional_usdt: float = 0.0,
    ) -> dict[str, Any]:
        now = utc_now()
        signal_id = self._new_signal_id(symbol)
        record = {
            "signal_id": signal_id,
            "symbol": normalize_crypto_symbol(symbol),
            "period": str(period or "1h"),
            "model": str(model or ""),
            "request_summary": request_summary,
            "response": response,
            "action": str(response.get("action") or "HOLD").upper(),
            "confidence": float(response.get("confidence", 0) or 0),
            "approval_status": approval_status,
            "approval_reason": approval_reason,
            "approved_notional_usdt": float(approved_notional_usdt or 0),
            "linked_order_id": "",
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_signals
                    (signal_id, symbol, period, model, request_summary_json, response_json,
                     action, confidence, approval_status, approval_reason,
                     approved_notional_usdt, linked_order_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["signal_id"],
                    record["symbol"],
                    record["period"],
                    record["model"],
                    safe_json(record["request_summary"]),
                    safe_json(record["response"]),
                    record["action"],
                    record["confidence"],
                    record["approval_status"],
                    record["approval_reason"],
                    record["approved_notional_usdt"],
                    record["linked_order_id"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
        return record

    def list_signals(self, limit: int = 100, offset: int = 0, symbol: str | None = None) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(0, int(offset or 0))
        where = ""
        params: list[Any] = []
        if symbol:
            where = "WHERE symbol = ?"
            params.append(normalize_crypto_symbol(symbol))
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM ai_signals {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM ai_signals {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return {
            "items": [self._row_to_record(row) for row in rows],
            "count": len(rows),
            "total": int(total or 0),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_signals WHERE signal_id = ?", (str(signal_id),)).fetchone()
        return self._row_to_record(row) if row else None

    def update_approval(
        self,
        signal_id: str,
        *,
        approval_status: str,
        approval_reason: str,
        approved_notional_usdt: float | None = None,
        linked_order_id: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_signal(signal_id)
        if not current:
            return None
        next_notional = current.get("approved_notional_usdt", 0.0) if approved_notional_usdt is None else approved_notional_usdt
        next_order_id = current.get("linked_order_id", "") if linked_order_id is None else linked_order_id
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_signals
                SET approval_status = ?,
                    approval_reason = ?,
                    approved_notional_usdt = ?,
                    linked_order_id = ?,
                    updated_at = ?
                WHERE signal_id = ?
                """,
                (
                    approval_status,
                    approval_reason,
                    float(next_notional or 0),
                    str(next_order_id or ""),
                    utc_now(),
                    str(signal_id),
                ),
            )
        return self.get_signal(signal_id)

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    period TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_summary_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    approval_status TEXT NOT NULL,
                    approval_reason TEXT DEFAULT '',
                    approved_notional_usdt REAL NOT NULL DEFAULT 0,
                    linked_order_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_signals_symbol_created
                    ON ai_signals(symbol, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_signals_action
                    ON ai_signals(action);
                CREATE INDEX IF NOT EXISTS idx_ai_signals_approval
                    ON ai_signals(approval_status);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        configure_sqlite_connection(conn)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "signal_id": row["signal_id"],
            "symbol": row["symbol"],
            "period": row["period"],
            "model": row["model"],
            "request_summary": json.loads(row["request_summary_json"] or "{}"),
            "response": json.loads(row["response_json"] or "{}"),
            "action": row["action"],
            "confidence": float(row["confidence"] or 0),
            "approval_status": row["approval_status"],
            "approval_reason": row["approval_reason"] or "",
            "approved_notional_usdt": float(row["approved_notional_usdt"] or 0),
            "linked_order_id": row["linked_order_id"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _new_signal_id(self, symbol: str) -> str:
        compact_symbol = normalize_crypto_symbol(symbol).replace("/", "")
        return f"AI_{compact_symbol}_{int(time.time() * 1000)}"


def validate_ai_advice(payload: dict[str, Any], expected_symbol: str = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object")
    expected = normalize_crypto_symbol(expected_symbol) if expected_symbol else ""
    raw_symbol = str(payload.get("symbol") or "").strip()
    symbol = normalize_crypto_symbol(raw_symbol or expected)
    expected = normalize_crypto_symbol(expected_symbol) if expected_symbol else symbol
    if expected and symbol != expected:
        raise ValueError(f"AI response symbol mismatch: {symbol} != {expected}")

    action = str(payload.get("action") or "").upper()
    if action not in {"BUY", "SELL", "HOLD"}:
        action = "HOLD"

    missing = [key for key in AI_SIGNAL_SCHEMA["required"] if key not in payload]
    confidence = _safe_float(payload.get("confidence"), default=0.0, minimum=0.0, maximum=1.0)
    suggested_notional = _safe_float(payload.get("suggested_notional_usdt"), default=0.0, minimum=0.0)
    max_loss = _safe_float(payload.get("max_loss_usdt"), default=0.0, minimum=0.0)
    risk_notes = payload.get("risk_notes") if isinstance(payload.get("risk_notes"), list) else []
    invalid_if = payload.get("invalid_if") if isinstance(payload.get("invalid_if"), list) else []
    reason = str(payload.get("reason") or "").strip()
    if missing:
        action = "HOLD"
        confidence = 0.0
        suggested_notional = 0.0
        max_loss = 0.0
        reason = (
            f"AI 返回格式不完整，缺少字段：{', '.join(missing)}。"
            "系统已按安全规则转为 HOLD，不会生成模拟订单。"
        )
        risk_notes = [*risk_notes, "AI 输出未完全符合本地结构化格式。"]
        invalid_if = [*invalid_if, "重新分析并获得完整结构化建议前保持观望。"]

    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "suggested_notional_usdt": suggested_notional,
        "max_loss_usdt": max_loss,
        "time_horizon": str(payload.get("time_horizon") or ""),
        "reason": reason,
        "risk_notes": [str(item) for item in risk_notes],
        "invalid_if": [str(item) for item in invalid_if],
    }


def _safe_float(value: Any, *, default: float = 0.0, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number
