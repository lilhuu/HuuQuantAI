"""Risk-budget based crypto position sizing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RiskBudgetConfig:
    risk_per_trade_pct: float = 0.02
    max_total_risk_pct: float = 0.06
    max_position_pct: float = 1.0
    max_leverage: float = 1.0
    min_position_value: float = 10.0


@dataclass
class PositionSize:
    risk_budget: float
    risk_per_unit: float
    quantity: float
    notional_value: float
    position_pct: float
    is_capped_by_total_risk: bool
    is_capped_by_position_limit: bool
    reason: str = ""


class RiskBudgetSizer:
    """Calculate size from maximum acceptable loss and stop distance."""

    def __init__(self, config: RiskBudgetConfig | None = None):
        self.config = config or RiskBudgetConfig()

    def calculate(
        self,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        current_positions_risk: float = 0.0,
    ) -> PositionSize:
        cfg = self.config
        equity = max(float(account_equity or 0), 0.0)
        entry = float(entry_price or 0)
        stop = float(stop_loss_price or 0)
        if equity <= 0:
            return self._zero("account equity is zero")
        if entry <= 0 or stop <= 0:
            return self._zero("entry price or stop loss price is invalid")

        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0:
            return self._zero("stop loss price equals entry price")

        raw_risk_budget = equity * max(cfg.risk_per_trade_pct, 0.0)
        max_total_risk = equity * max(cfg.max_total_risk_pct, 0.0)
        available_risk = max(max_total_risk - max(float(current_positions_risk or 0), 0.0), 0.0)
        risk_budget = min(raw_risk_budget, available_risk)
        capped_total = risk_budget < raw_risk_budget
        if risk_budget <= 0:
            return PositionSize(0, risk_per_unit, 0, 0, 0, True, False, "total risk budget exhausted")

        quantity = risk_budget / risk_per_unit
        notional = quantity * entry
        max_notional = equity * max(cfg.max_position_pct, 0.0) * max(cfg.max_leverage, 0.0)
        capped_position = False
        if max_notional > 0 and notional > max_notional:
            notional = max_notional
            quantity = notional / entry
            capped_position = True

        if notional < cfg.min_position_value:
            return PositionSize(risk_budget, risk_per_unit, 0, 0, 0, capped_total, capped_position, "below minimum position value")

        reasons = []
        if capped_total:
            reasons.append("total risk cap")
        if capped_position:
            reasons.append("position cap")
        if not reasons:
            reasons.append("risk budget")
        return PositionSize(
            risk_budget=round(risk_budget, 8),
            risk_per_unit=round(risk_per_unit, 8),
            quantity=round(quantity, 8),
            notional_value=round(notional, 8),
            position_pct=round(notional / equity if equity else 0.0, 8),
            is_capped_by_total_risk=capped_total,
            is_capped_by_position_limit=capped_position,
            reason=" | ".join(reasons),
        )

    def calculate_total_risk(self, positions: list[dict[str, Any]]) -> float:
        total = 0.0
        for position in positions or []:
            entry = float(position.get("entry_price", position.get("avg_price", 0)) or 0)
            stop = float(position.get("stop_loss_price", 0) or 0)
            quantity = float(position.get("quantity", 0) or 0)
            if entry > 0 and stop > 0 and quantity > 0:
                total += abs(entry - stop) * quantity
        return total

    def _zero(self, reason: str) -> PositionSize:
        return PositionSize(0, 0, 0, 0, 0, False, False, reason)
