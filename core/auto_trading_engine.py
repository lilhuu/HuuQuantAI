"""Paper-only automatic trading control loop for crypto strategies.

The engine owns runtime state and order decision rules. It never talks to a
real exchange; callers provide strategy results and execute returned paper
orders through CryptoPaperBroker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from core.crypto_market_data_provider import normalize_crypto_symbol


AutoTradingState = Literal["stopped", "running", "paused", "blocked"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_strategies(symbols: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": "auto_rsi",
            "type": "rsi",
            "symbols": symbols,
            "weight": 1.0,
            "enabled": True,
            "parameters": {"period": 14, "oversold": 30, "overbought": 70, "position_ratio": 0.08},
        },
        {
            "strategy_id": "auto_macd",
            "type": "macd",
            "symbols": symbols,
            "weight": 0.8,
            "enabled": True,
            "parameters": {"position_ratio": 0.06},
        },
        {
            "strategy_id": "auto_momentum",
            "type": "momentum",
            "symbols": symbols,
            "weight": 0.7,
            "enabled": True,
            "parameters": {"lookback_period": 20, "buy_threshold": 0.025, "sell_threshold": -0.02, "position_ratio": 0.05},
        },
    ]


@dataclass
class AutoTradingConfig:
    enabled: bool = False
    mode: str = "paper"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    period: str = "1h"
    timeframes: list[str] = field(default_factory=list)
    scan_interval_seconds: int = 30
    max_positions: int = 3
    per_trade_position_ratio: float = 0.1
    max_order_notional: float = 1000.0
    min_order_notional: float = 10.0
    confidence_threshold: float = 0.35
    real_trading_enabled: bool = False
    strategies: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AutoTradingConfig":
        data = dict(payload or {})
        symbols = [
            symbol
            for symbol in (normalize_crypto_symbol(item) for item in data.get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]))
            if symbol
        ]
        if not symbols:
            symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

        strategies = list(data.get("strategies") or [])
        if not strategies:
            strategies = _default_strategies(symbols)

        return cls(
            enabled=bool(data.get("enabled", False)),
            mode="paper",
            symbols=symbols,
            period=str(data.get("period") or "1h"),
            timeframes=[str(item) for item in data.get("timeframes", []) if str(item or "").strip()],
            scan_interval_seconds=max(5, min(int(data.get("scan_interval_seconds", 30) or 30), 3600)),
            max_positions=max(1, min(int(data.get("max_positions", 3) or 3), 20)),
            per_trade_position_ratio=max(0.001, min(float(data.get("per_trade_position_ratio", 0.1) or 0.1), 1.0)),
            max_order_notional=max(1.0, float(data.get("max_order_notional", 1000.0) or 1000.0)),
            min_order_notional=max(0.0, float(data.get("min_order_notional", 10.0) or 10.0)),
            confidence_threshold=max(0.0, min(float(data.get("confidence_threshold", 0.35) or 0.35), 1.0)),
            real_trading_enabled=bool(data.get("real_trading_enabled", False)),
            strategies=strategies,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": "paper",
            "symbols": list(self.symbols),
            "period": self.period,
            "timeframes": list(self.timeframes),
            "scan_interval_seconds": self.scan_interval_seconds,
            "max_positions": self.max_positions,
            "per_trade_position_ratio": self.per_trade_position_ratio,
            "max_order_notional": self.max_order_notional,
            "min_order_notional": self.min_order_notional,
            "confidence_threshold": self.confidence_threshold,
            "real_trading_enabled": False,
            "strategies": list(self.strategies),
        }


class AutoTradingEngine:
    """Runtime state and paper-only order decision rules."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = AutoTradingConfig.from_dict(config)
        self.state: AutoTradingState = "stopped"
        self.last_run_at = ""
        self.last_message = "auto trading is stopped"
        self.cycle_count = 0
        self.signal_count = 0
        self.order_count = 0
        self.last_decisions: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []
        self._log("INFO", "initialized", "Paper auto trading engine initialized")

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = {**self.config.to_dict(), **(payload or {})}
        self.config = AutoTradingConfig.from_dict(merged)
        if self.config.real_trading_enabled:
            self.config.real_trading_enabled = False
            self._log("WARNING", "real_trading_blocked", "real_trading_enabled was ignored; paper mode is mandatory")
        self._log("INFO", "config_updated", "Auto trading config updated")
        return self.status()

    def start(self) -> dict[str, Any]:
        if self.config.real_trading_enabled:
            self.state = "blocked"
            self.last_message = "real trading is blocked; paper mode only"
            self._log("ERROR", "start_blocked", self.last_message)
            return self.status()
        self.config.enabled = True
        self.state = "running"
        self.last_message = "auto trading is running in paper mode"
        self._log("INFO", "started", self.last_message)
        return self.status()

    def pause(self) -> dict[str, Any]:
        self.state = "paused"
        self.config.enabled = False
        self.last_message = "auto trading is paused"
        self._log("INFO", "paused", self.last_message)
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.state = "stopped"
        self.config.enabled = False
        self.last_message = "auto trading is stopped"
        self._log("INFO", "stopped", self.last_message)
        return self.status()

    def build_order_decisions(
        self,
        strategy_result: dict[str, Any],
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        *,
        place_orders: bool = True,
    ) -> list[dict[str, Any]]:
        self.last_run_at = _now()
        self.cycle_count += 1
        self.signal_count += len(strategy_result.get("signals") or [])

        price_by_symbol = {
            str(item.get("symbol") or ""): float(item.get("price", 0) or 0)
            for item in strategy_result.get("summary", [])
        }
        candidates = self._candidates(strategy_result)
        position_by_symbol = {str(item.get("symbol") or ""): item for item in positions or []}
        equity = float(account.get("equity") or account.get("cash") or 0)
        cash = float(account.get("available_cash") or account.get("cash") or 0)
        current_position_count = len([item for item in positions or [] if float(item.get("quantity", 0) or 0) > 0])

        decisions: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            symbol = normalize_crypto_symbol(str(candidate.get("symbol") or ""))
            action = str(candidate.get("action") or "").upper()
            if not symbol or action not in {"BUY", "SELL"} or (symbol, action) in seen:
                continue
            seen.add((symbol, action))

            price = float(candidate.get("price") or price_by_symbol.get(symbol) or 0)
            confidence = float(candidate.get("confidence") or candidate.get("score") or 0)
            strategy_id = str(candidate.get("strategy_id") or candidate.get("source_strategy_ids", ["auto"])[0] or "auto")
            reason = str(candidate.get("reason") or "strategy signal")
            decision = self._build_one_decision(
                symbol=symbol,
                action=action,
                price=price,
                confidence=confidence,
                strategy_id=strategy_id,
                reason=reason,
                candidate=candidate,
                equity=equity,
                cash=cash,
                positions=position_by_symbol,
                current_position_count=current_position_count,
                place_orders=place_orders,
            )
            decisions.append(decision)
            if decision["status"] == "ready" and action == "BUY":
                cash -= decision["notional"]
                current_position_count += 1

        self.last_decisions = decisions[-50:]
        self.last_message = f"scan completed: {len(decisions)} decisions"
        self._log("INFO", "scan_completed", self.last_message, {"decision_count": len(decisions), "place_orders": place_orders})
        return decisions

    def record_order_result(self, decision: dict[str, Any], order: dict[str, Any]) -> None:
        if str(order.get("status") or "").lower() in {"filled", "partial_filled"}:
            self.order_count += 1
        self._log(
            "INFO" if order.get("status") != "rejected" else "WARNING",
            "paper_order_result",
            str(order.get("message") or "paper order processed"),
            {"decision": decision, "order": order},
        )

    def record_error(self, message: str, payload: dict[str, Any] | None = None) -> None:
        self.last_message = message
        self._log("ERROR", "cycle_failed", message, payload)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "enabled": bool(self.config.enabled and self.state == "running"),
            "mode": "paper",
            "config": self.config.to_dict(),
            "last_run_at": self.last_run_at,
            "last_message": self.last_message,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "order_count": self.order_count,
            "last_decisions": list(self.last_decisions),
            "logs": self.get_logs(50),
            "real_trading_enabled": False,
        }

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 100), 500))
        return self.logs[-safe_limit:]

    def _build_one_decision(
        self,
        *,
        symbol: str,
        action: str,
        price: float,
        confidence: float,
        strategy_id: str,
        reason: str,
        candidate: dict[str, Any],
        equity: float,
        cash: float,
        positions: dict[str, dict[str, Any]],
        current_position_count: int,
        place_orders: bool,
    ) -> dict[str, Any]:
        position = positions.get(symbol) or {}
        quantity_held = float(position.get("quantity", 0) or 0)
        base = {
            "timestamp": _now(),
            "symbol": symbol,
            "action": action,
            "price": price,
            "quantity": 0.0,
            "notional": 0.0,
            "strategy_id": strategy_id,
            "confidence": confidence,
            "reason": reason,
            "status": "skipped",
            "message": "",
            "place_orders": bool(place_orders),
        }

        if self.config.real_trading_enabled:
            base["message"] = "real trading is blocked"
            return base
        if price <= 0:
            base["message"] = "missing executable price"
            return base
        if confidence < self.config.confidence_threshold:
            base["message"] = f"confidence below threshold {self.config.confidence_threshold:.2f}"
            return base
        if not place_orders:
            base["status"] = "simulated"
            base["message"] = "decision preview only; no paper order sent"

        if action == "BUY":
            if quantity_held > 0:
                base["message"] = "position already exists"
                return base
            if current_position_count >= self.config.max_positions:
                base["message"] = "max open positions reached"
                return base
            ratio = float(candidate.get("adjusted_position_ratio") or self.config.per_trade_position_ratio)
            ratio = max(0.001, min(ratio, self.config.per_trade_position_ratio, 1.0))
            notional = min(equity * ratio, self.config.max_order_notional, cash)
            if notional < self.config.min_order_notional:
                base["message"] = "notional below minimum or cash unavailable"
                return base
            base["quantity"] = round(notional / price, 8)
            base["notional"] = round(base["quantity"] * price, 8)
            if base["quantity"] <= 0:
                base["message"] = "quantity rounded to zero"
                return base
        else:
            if quantity_held <= 0:
                base["message"] = "no position to sell; short selling disabled"
                return base
            base["quantity"] = round(quantity_held, 8)
            base["notional"] = round(base["quantity"] * price, 8)

        if place_orders:
            base["status"] = "ready"
            base["message"] = "ready for paper order"
        return base

    def _candidates(self, strategy_result: dict[str, Any]) -> list[dict[str, Any]]:
        winners = [dict(item) for item in strategy_result.get("winners", []) if str(item.get("action") or "").upper() in {"BUY", "SELL"}]
        if winners:
            return winners
        return [
            dict(item)
            for item in strategy_result.get("summary", [])
            if str(item.get("action") or "").upper() in {"BUY", "SELL"}
        ]

    def _log(self, level: str, event: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self.logs.append(
            {
                "timestamp": _now(),
                "level": level,
                "event": event,
                "message": message,
                "payload": payload or {},
            }
        )
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]
