"""Runtime state for AI-supervised paper trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AiPaperSupervisorRuntime:
    """Track candle deduplication, provider health, and the latest AI verdict."""

    max_provider_failures: int = 3
    last_candle_by_symbol: dict[str, str] = field(default_factory=dict)
    provider_failure_count: int = 0
    blocked_reason: str = ""
    last_decision_at: str = ""
    last_candle_at: str = ""
    last_signal_id: str = ""
    last_action: str = ""

    def should_evaluate(self, symbol: str, candle_time: str) -> bool:
        symbol_key = str(symbol or "").strip().upper()
        candle_key = str(candle_time or "").strip()
        return bool(symbol_key and candle_key and self.last_candle_by_symbol.get(symbol_key) != candle_key)

    def record_attempt(self, symbol: str, candle_time: str) -> None:
        """Mark a closed candle before calling the provider so failures are not retried on it."""
        symbol_key = str(symbol or "").strip().upper()
        candle_key = str(candle_time or "").strip()
        if symbol_key and candle_key:
            self.last_candle_by_symbol[symbol_key] = candle_key

    def record_signal(self, symbol: str, candle_time: str, signal_id: str, action: str) -> None:
        candle_key = str(candle_time or "").strip()
        self.record_attempt(symbol, candle_time)
        self.provider_failure_count = 0
        self.blocked_reason = ""
        self.last_decision_at = _now()
        self.last_candle_at = candle_key
        self.last_signal_id = str(signal_id or "")
        self.last_action = str(action or "HOLD").upper()

    def record_provider_failure(self, reason: str) -> bool:
        self.provider_failure_count += 1
        self.blocked_reason = str(reason or "AI provider unavailable")
        self.last_decision_at = _now()
        self.last_action = "HOLD"
        return self.provider_failure_count >= max(1, int(self.max_provider_failures or 3))

    def status(self, *, model: str = "", fallback_model: str = "", enabled: bool = False) -> dict[str, Any]:
        return {
            "enabled": bool(enabled),
            "model": str(model or ""),
            "fallback_model": str(fallback_model or ""),
            "last_decision_at": self.last_decision_at,
            "last_candle_at": self.last_candle_at,
            "last_signal_id": self.last_signal_id,
            "last_action": self.last_action,
            "provider_failure_count": int(self.provider_failure_count),
            "blocked_reason": self.blocked_reason,
            "evaluated_candles": dict(self.last_candle_by_symbol),
        }
