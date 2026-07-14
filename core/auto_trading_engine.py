"""Paper-only automatic trading control loop for crypto strategies.

The engine owns runtime state and order decision rules. It never talks to a
real exchange; callers provide strategy results and execute returned paper
orders through CryptoPaperBroker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

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


def _config_value(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    return default if value is None else value


@dataclass
class AutoTradingConfig:
    enabled: bool = False
    mode: str = "paper"
    decision_mode: str = "strategy"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    period: str = "1h"
    timeframes: list[str] = field(default_factory=list)
    scan_interval_seconds: int = 30
    max_positions: int = 3
    per_trade_position_ratio: float = 0.1
    max_order_notional: float = 1000.0
    min_order_notional: float = 10.0
    confidence_threshold: float = 0.35
    ai_model: str = "deepseek-v4-pro"
    ai_fallback_model: str = "deepseek-v4-flash"
    ai_on_new_candle_only: bool = True
    ai_confidence_threshold: float = 0.65
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    max_daily_loss: float = 0.0
    max_consecutive_losses: int = 0
    cooldown_minutes: int = 30
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
            decision_mode="ai_supervised" if str(data.get("decision_mode") or "strategy") == "ai_supervised" else "strategy",
            symbols=symbols,
            period=str(data.get("period") or "1h"),
            timeframes=[str(item) for item in data.get("timeframes", []) if str(item or "").strip()],
            scan_interval_seconds=max(5, min(int(_config_value(data, "scan_interval_seconds", 30)), 3600)),
            max_positions=max(1, min(int(_config_value(data, "max_positions", 3)), 20)),
            per_trade_position_ratio=max(0.001, min(float(_config_value(data, "per_trade_position_ratio", 0.1)), 1.0)),
            max_order_notional=max(1.0, float(data.get("max_order_notional", 1000.0) or 1000.0)),
            min_order_notional=max(0.0, float(data.get("min_order_notional", 10.0) or 10.0)),
            confidence_threshold=max(0.0, min(float(data.get("confidence_threshold", 0.35) or 0.35), 1.0)),
            ai_model=str(data.get("ai_model") or "deepseek-v4-pro"),
            ai_fallback_model=str(data.get("ai_fallback_model") or "deepseek-v4-flash"),
            ai_on_new_candle_only=bool(data.get("ai_on_new_candle_only", True)),
            ai_confidence_threshold=max(0.0, min(float(data.get("ai_confidence_threshold", 0.65) or 0.65), 1.0)),
            stop_loss_pct=max(0.001, min(float(data.get("stop_loss_pct", 0.02) or 0.02), 0.2)),
            take_profit_pct=max(0.001, min(float(data.get("take_profit_pct", 0.04) or 0.04), 0.5)),
            max_daily_loss=max(0.0, float(data.get("max_daily_loss", 0.0) or 0.0)),
            max_consecutive_losses=max(0, int(data.get("max_consecutive_losses", 0) or 0)),
            cooldown_minutes=max(1, min(int(_config_value(data, "cooldown_minutes", 30)), 24 * 60)),
            real_trading_enabled=False,
            strategies=strategies,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": "paper",
            "decision_mode": self.decision_mode,
            "symbols": list(self.symbols),
            "period": self.period,
            "timeframes": list(self.timeframes),
            "scan_interval_seconds": self.scan_interval_seconds,
            "max_positions": self.max_positions,
            "per_trade_position_ratio": self.per_trade_position_ratio,
            "max_order_notional": self.max_order_notional,
            "min_order_notional": self.min_order_notional,
            "confidence_threshold": self.confidence_threshold,
            "ai_model": self.ai_model,
            "ai_fallback_model": self.ai_fallback_model,
            "ai_on_new_candle_only": self.ai_on_new_candle_only,
            "ai_confidence_threshold": self.ai_confidence_threshold,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "max_daily_loss": self.max_daily_loss,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_minutes": self.cooldown_minutes,
            "real_trading_enabled": False,
            "strategies": list(self.strategies),
        }


@dataclass
class RiskState:
    """Runtime risk state for automatic paper trading."""

    trading_day: str = ""
    day_start_equity: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    cooldown_until: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RiskState":
        data = dict(payload or {})
        return cls(
            trading_day=str(data.get("trading_day") or ""),
            day_start_equity=float(data.get("day_start_equity") or 0),
            daily_pnl=float(data.get("daily_pnl") or 0),
            consecutive_losses=max(int(data.get("consecutive_losses") or 0), 0),
            kill_switch_active=bool(data.get("kill_switch_active", False)),
            cooldown_until=str(data.get("cooldown_until") or ""),
            reason=str(data.get("reason") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_day": self.trading_day,
            "day_start_equity": round(float(self.day_start_equity or 0.0), 8),
            "daily_pnl": round(float(self.daily_pnl or 0.0), 8),
            "consecutive_losses": int(self.consecutive_losses or 0),
            "kill_switch_active": bool(self.kill_switch_active),
            "cooldown_until": self.cooldown_until,
            "reason": self.reason,
        }


class DecisionPipeline:
    """Stage-by-stage paper order decision gate."""

    def __init__(self, config: AutoTradingConfig, risk_state: RiskState, cooldown_active: bool) -> None:
        self.config = config
        self.risk_state = risk_state
        self.cooldown_active = cooldown_active

    def build_one(
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
        steps: list[dict[str, Any]] = []
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
            "steps": steps,
        }

        if self.config.real_trading_enabled:
            base["message"] = "real trading is blocked"
            steps.append(self._step("real_trading_gate", "fail", base["message"]))
            return base
        steps.append(self._step("real_trading_gate", "pass", "paper mode enforced"))
        if self.cooldown_active:
            base["message"] = f"risk cooldown active until {self.risk_state.cooldown_until}"
            steps.append(self._step("risk_cooldown", "fail", base["message"]))
            return base
        steps.append(self._step("risk_cooldown", "pass", "no active cooldown"))
        if self.risk_state.kill_switch_active:
            base["message"] = self.risk_state.reason or "risk kill switch active"
            steps.append(self._step("kill_switch", "fail", base["message"]))
            return base
        steps.append(self._step("kill_switch", "pass", "kill switch inactive"))
        if price <= 0:
            base["message"] = "missing executable price"
            steps.append(self._step("market_data", "fail", base["message"]))
            return base
        steps.append(self._step("market_data", "pass", "executable price available"))
        if confidence < self.config.confidence_threshold:
            base["message"] = f"confidence below threshold {self.config.confidence_threshold:.2f}"
            steps.append(self._step("confidence", "fail", base["message"]))
            return base
        steps.append(self._step("confidence", "pass", f"{confidence:.2f} >= {self.config.confidence_threshold:.2f}"))
        if not place_orders:
            base["status"] = "simulated"
            base["message"] = "decision preview only; no paper order sent"
            steps.append(self._step("submit_mode", "skip", base["message"]))
        else:
            steps.append(self._step("submit_mode", "pass", "paper order submission requested"))

        if action == "BUY":
            self._apply_buy_gates(base, steps, quantity_held, current_position_count, equity, cash, price, candidate)
        else:
            self._apply_sell_gates(base, steps, quantity_held, price, candidate)

        if base["status"] == "skipped" and not base["message"]:
            if place_orders:
                base["status"] = "ready"
                base["message"] = "ready for paper order"
                steps.append(self._step("submit", "pass", base["message"]))
        return base

    def _apply_buy_gates(
        self,
        base: dict[str, Any],
        steps: list[dict[str, Any]],
        quantity_held: float,
        current_position_count: int,
        equity: float,
        cash: float,
        price: float,
        candidate: dict[str, Any],
    ) -> None:
        if quantity_held > 0:
            base["message"] = "position already exists"
            steps.append(self._step("duplicate_position", "fail", base["message"]))
            return
        steps.append(self._step("duplicate_position", "pass", "no existing position"))
        if current_position_count >= self.config.max_positions:
            base["message"] = "max open positions reached"
            steps.append(self._step("max_positions", "fail", base["message"]))
            return
        steps.append(self._step("max_positions", "pass", f"{current_position_count} < {self.config.max_positions}"))
        ratio = float(candidate.get("adjusted_position_ratio") or self.config.per_trade_position_ratio)
        ratio = max(0.001, min(ratio, self.config.per_trade_position_ratio, 1.0))
        notional = min(equity * ratio, self.config.max_order_notional, cash)
        if notional < self.config.min_order_notional:
            base["message"] = "notional below minimum or cash unavailable"
            steps.append(self._step("notional", "fail", base["message"]))
            return
        steps.append(self._step("notional", "pass", f"approved notional {notional:.2f}"))
        base["quantity"] = round(notional / price, 8)
        base["notional"] = round(base["quantity"] * price, 8)
        if base["quantity"] <= 0:
            base["message"] = "quantity rounded to zero"
            steps.append(self._step("quantity", "fail", base["message"]))
            return
        steps.append(self._step("quantity", "pass", f"quantity {base['quantity']}"))

    def _apply_sell_gates(
        self,
        base: dict[str, Any],
        steps: list[dict[str, Any]],
        quantity_held: float,
        price: float,
        candidate: dict[str, Any],
    ) -> None:
        if quantity_held <= 0:
            base["message"] = "no position to sell; short selling disabled"
            steps.append(self._step("short_selling", "fail", base["message"]))
            return
        steps.append(self._step("short_selling", "pass", "existing long position available"))
        sell_quantity = quantity_held
        if "approved_notional_usdt" in candidate:
            approved_notional = max(float(candidate.get("approved_notional_usdt") or 0), 0.0)
            sell_quantity = min(quantity_held, approved_notional / price)
            if sell_quantity <= 0:
                base["message"] = "approved sell notional is zero"
                steps.append(self._step("approved_notional", "fail", base["message"]))
                return
            steps.append(
                self._step(
                    "approved_notional",
                    "pass",
                    f"sell notional capped at {approved_notional:.2f}",
                )
            )
        base["quantity"] = round(sell_quantity, 8)
        base["notional"] = round(base["quantity"] * price, 8)
        steps.append(self._step("quantity", "pass", f"sell quantity {base['quantity']}"))

    def _step(self, name: str, status: str, reason: str) -> dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "reason": reason,
            "timestamp": _now(),
        }


class AutoTradingEngine:
    """Runtime state and paper-only order decision rules."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        risk_state_loader: Callable[[], dict[str, Any]] | None = None,
        risk_state_saver: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = AutoTradingConfig.from_dict(config)
        self.state: AutoTradingState = "stopped"
        self.last_run_at = ""
        self.last_message = "auto trading is stopped"
        self.cycle_count = 0
        self.signal_count = 0
        self.order_count = 0
        self.last_decisions: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []
        self._risk_state_saver = risk_state_saver
        self.risk_state = RiskState.from_dict(risk_state_loader() if risk_state_loader else None)
        self.loop_running = False
        self.next_run_at = ""
        self.last_error_type = ""
        self.ai_supervisor_status: dict[str, Any] = {}
        if self.risk_state.kill_switch_active and self._cooldown_active():
            self.state = "paused"
            self.config.enabled = False
            self.last_message = self.risk_state.reason or "risk cooldown restored"
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
        if self._cooldown_active():
            self.state = "paused"
            self.last_message = f"auto trading is cooling down until {self.risk_state.cooldown_until}"
            self._log("WARNING", "start_blocked_by_cooldown", self.last_message, {"risk_state": self.risk_state.to_dict()})
            return self.status()
        self.risk_state.kill_switch_active = False
        self.risk_state.reason = ""
        self._persist_risk_state()
        self.state = "running"
        self.last_message = "auto trading is running in paper mode"
        self.last_error_type = ""
        self._log("INFO", "started", self.last_message)
        return self.status()

    def pause(self) -> dict[str, Any]:
        self.state = "paused"
        self.config.enabled = False
        self.loop_running = False
        self.next_run_at = ""
        self.last_message = "auto trading is paused"
        self._log("INFO", "paused", self.last_message)
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.state = "stopped"
        self.config.enabled = False
        self.loop_running = False
        self.next_run_at = ""
        self.last_message = "auto trading is stopped"
        self._log("INFO", "stopped", self.last_message)
        return self.status()

    def block(self, reason: str, event: str = "blocked") -> dict[str, Any]:
        self.state = "blocked"
        self.config.enabled = False
        self.loop_running = False
        self.next_run_at = ""
        self.last_message = str(reason or "automatic paper trading blocked")
        self._log("ERROR", event, self.last_message)
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
        self._update_risk_state(account)

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
            realized_pnl = float(order.get("realized_pnl", 0) or 0)
            if realized_pnl < 0:
                self.risk_state.consecutive_losses += 1
                if self.config.max_consecutive_losses and self.risk_state.consecutive_losses >= self.config.max_consecutive_losses:
                    self._activate_kill_switch(
                        f"consecutive losses reached {self.risk_state.consecutive_losses}/{self.config.max_consecutive_losses}"
                    )
            elif realized_pnl > 0:
                self.risk_state.consecutive_losses = 0
            self._persist_risk_state()
        self._log(
            "INFO" if order.get("status") != "rejected" else "WARNING",
            "paper_order_result",
            str(order.get("message") or "paper order processed"),
            {"decision": decision, "order": order},
        )

    def record_error(self, message: str, payload: dict[str, Any] | None = None) -> None:
        self.last_message = message
        self.last_error_type = str((payload or {}).get("type") or "RuntimeError")
        self._log("ERROR", "cycle_failed", message, payload)

    def mark_loop(self, *, running: bool, next_run_at: str = "") -> None:
        self.loop_running = bool(running)
        self.next_run_at = next_run_at if running else ""

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
            "risk_state": self.risk_state.to_dict(),
            "real_trading_enabled": False,
            "loop_running": bool(self.loop_running),
            "next_run_at": self.next_run_at,
            "last_error_type": self.last_error_type,
            "ai_supervisor": dict(self.ai_supervisor_status),
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
        pipeline = DecisionPipeline(self.config, self.risk_state, self._cooldown_active())
        return pipeline.build_one(
            symbol=symbol,
            action=action,
            price=price,
            confidence=confidence,
            strategy_id=strategy_id,
            reason=reason,
            candidate=candidate,
            equity=equity,
            cash=cash,
            positions=positions,
            current_position_count=current_position_count,
            place_orders=place_orders,
        )

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

    def _update_risk_state(self, account: dict[str, Any]) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        equity = float(account.get("equity") or account.get("cash") or 0.0)
        if self.risk_state.trading_day != today:
            self.risk_state.trading_day = today
            self.risk_state.day_start_equity = equity
            self.risk_state.daily_pnl = 0.0
        if self.risk_state.day_start_equity <= 0 and equity > 0:
            self.risk_state.day_start_equity = equity
        self.risk_state.daily_pnl = equity - float(self.risk_state.day_start_equity or equity)
        if self.config.max_daily_loss and self.risk_state.daily_pnl <= -abs(self.config.max_daily_loss):
            self._activate_kill_switch(
                f"daily loss {self.risk_state.daily_pnl:.2f} reached limit -{abs(self.config.max_daily_loss):.2f}"
            )
        else:
            self._persist_risk_state()

    def _activate_kill_switch(self, reason: str) -> None:
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.config.cooldown_minutes)
        self.risk_state.kill_switch_active = True
        self.risk_state.cooldown_until = cooldown_until.isoformat()
        self.risk_state.reason = reason
        self.state = "paused"
        self.config.enabled = False
        self.last_message = reason
        self._log("ERROR", "risk_kill_switch", reason, {"risk_state": self.risk_state.to_dict()})
        self._persist_risk_state()

    def _cooldown_active(self) -> bool:
        if not self.risk_state.cooldown_until:
            return False
        try:
            until = datetime.fromisoformat(self.risk_state.cooldown_until)
        except ValueError:
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        active = datetime.now(timezone.utc) < until
        if not active and self.risk_state.kill_switch_active:
            self.risk_state.kill_switch_active = False
            self.risk_state.cooldown_until = ""
            self.risk_state.reason = ""
            self._log("INFO", "risk_cooldown_expired", "risk cooldown expired")
            self._persist_risk_state()
        return active

    def _persist_risk_state(self) -> None:
        if self._risk_state_saver is not None:
            self._risk_state_saver(self.risk_state.to_dict())

    def _decision_step(self, name: str, status: str, reason: str) -> dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "reason": reason,
            "timestamp": _now(),
        }
