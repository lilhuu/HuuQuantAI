"""Shadow trading with order-book impact estimation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FillResult:
    filled_quantity: float
    average_price: float
    total_cost: float
    slippage_pct: float
    levels_consumed: int
    remaining_quantity: float
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_fully_filled(self) -> bool:
        return self.remaining_quantity <= 1e-8


class OrderbookImpactCalculator:
    """Estimate fill price from visible order-book depth."""

    def simulate_fill(
        self,
        order_book: dict[str, Any],
        side: str,
        quantity: float,
        max_slippage_pct: float = 5.0,
    ) -> FillResult:
        side = str(side or "").upper()
        levels = order_book.get("asks" if side == "BUY" else "bids", []) if order_book else []
        quantity = max(float(quantity or 0), 0.0)
        if quantity <= 0 or not levels:
            return FillResult(0.0, 0.0, 0.0, 0.0, 0, quantity, [])

        best_price = float(levels[0][0] or 0)
        remaining = quantity
        filled = 0.0
        total_cost = 0.0
        details: list[dict[str, Any]] = []
        for level_index, level in enumerate(levels, start=1):
            price = float(level[0] or 0)
            amount = float(level[1] or 0)
            if price <= 0 or amount <= 0 or remaining <= 0:
                continue
            take = min(remaining, amount)
            trial_filled = filled + take
            trial_cost = total_cost + take * price
            avg_price = trial_cost / trial_filled if trial_filled else 0.0
            slip = self._slippage(side, best_price, avg_price)
            if slip > max_slippage_pct:
                break
            filled = trial_filled
            total_cost = trial_cost
            remaining -= take
            details.append({"level": level_index, "price": price, "filled": round(take, 8), "cost": round(take * price, 8)})

        average_price = total_cost / filled if filled else 0.0
        return FillResult(
            filled_quantity=round(filled, 8),
            average_price=round(average_price, 8),
            total_cost=round(total_cost, 8),
            slippage_pct=round(self._slippage(side, best_price, average_price), 8),
            levels_consumed=len(details),
            remaining_quantity=round(remaining, 8),
            details=details,
        )

    def _slippage(self, side: str, best_price: float, average_price: float) -> float:
        if best_price <= 0 or average_price <= 0:
            return 0.0
        if side == "BUY":
            return max((average_price - best_price) / best_price * 100, 0.0)
        return max((best_price - average_price) / best_price * 100, 0.0)


@dataclass
class ShadowPosition:
    symbol: str
    quantity: float
    avg_price: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    created_at: str = ""
    signal_source: str = ""
    estimated_slippage_pct: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.avg_price


class ShadowTradingEngine:
    """Track simulated shadow positions without sending real orders."""

    def __init__(self, market_data_provider: Any, impact_calculator: OrderbookImpactCalculator | None = None):
        self.provider = market_data_provider
        self.impact = impact_calculator or OrderbookImpactCalculator()
        self.shadow_positions: dict[str, ShadowPosition] = {}
        self.trade_log: list[dict[str, Any]] = []

    def execute_shadow_trade(
        self,
        symbol: str,
        action: str,
        quantity: float,
        strategy_id: str,
        sl_price: float | None = None,
        tp_price: float | None = None,
    ) -> dict[str, Any]:
        action = str(action or "").upper()
        try:
            order_book = self.provider.fetch_order_book(symbol, limit=20)
        except Exception:
            order_book = None

        if order_book:
            fill = self.impact.simulate_fill(order_book, action, quantity)
        else:
            reference = self._reference_price(symbol)
            slipped = reference * (1.0005 if action == "BUY" else 0.9995)
            fill = FillResult(float(quantity or 0), slipped, float(quantity or 0) * slipped, 0.05, 0, 0.0, [])

        if action == "BUY" and fill.filled_quantity > 0:
            self.shadow_positions[symbol] = ShadowPosition(
                symbol=symbol,
                quantity=fill.filled_quantity,
                avg_price=fill.average_price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                created_at=self._now(),
                signal_source=strategy_id,
                estimated_slippage_pct=fill.slippage_pct,
            )
        elif action == "SELL":
            self.shadow_positions.pop(symbol, None)

        record = {
            "timestamp": self._now(),
            "symbol": symbol,
            "action": action,
            "quantity": fill.filled_quantity,
            "price": fill.average_price,
            "slippage_pct": fill.slippage_pct,
            "levels_consumed": fill.levels_consumed,
            "remaining_quantity": fill.remaining_quantity,
            "strategy_id": strategy_id,
            "orderbook_available": bool(order_book),
        }
        self.trade_log.append(record)
        return record

    def get_positions(self) -> list[dict[str, Any]]:
        return [position.__dict__ | {"notional": position.notional} for position in self.shadow_positions.values()]

    def _reference_price(self, symbol: str) -> float:
        try:
            quotes = self.provider.fetch_quotes([symbol])
            if quotes:
                return float(quotes[0].get("price", 0) or 0)
        except Exception:
            return 0.0
        return 0.0

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
