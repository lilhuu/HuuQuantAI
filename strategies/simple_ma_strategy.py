"""Simple moving-average strategy for quote polling."""

from datetime import datetime
from typing import Dict, List, Optional

from strategies.base_strategy import Signal


class SimpleMAStrategy:
    """A minimal fast/slow moving-average strategy."""

    def __init__(
        self,
        fast_period: int = 5,
        slow_period: int = 20,
        initial_capital: float = 100000,
        trade_pct: float = 0.1,
        lot_size: int = 100,
        emit_repeated_signals: bool = False,
        name: str = "simple_ma_strategy",
    ):
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("fast_period and slow_period must be positive")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be smaller than slow_period")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.initial_capital = initial_capital
        self.trade_pct = trade_pct
        self.lot_size = lot_size
        self.emit_repeated_signals = emit_repeated_signals
        self.name = name

        self.price_history: Dict[str, List[float]] = {}
        self.last_actions: Dict[str, str] = {}

    def calculate_signal(self, symbol: str, current_price: float) -> str:
        """Calculate a BUY/SELL/HOLD decision for one symbol."""
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        self.price_history[symbol].append(float(current_price))

        max_history = self.slow_period * 2
        if len(self.price_history[symbol]) > max_history:
            self.price_history[symbol] = self.price_history[symbol][-max_history:]

        if len(self.price_history[symbol]) >= self.slow_period:
            prices = self.price_history[symbol]
            fast_ma = sum(prices[-self.fast_period:]) / self.fast_period
            slow_ma = sum(prices[-self.slow_period:]) / self.slow_period

            if fast_ma > slow_ma:
                return "BUY"
            if fast_ma < slow_ma:
                return "SELL"

        return "HOLD"

    def calculate_signals(self, quotes_dict: Dict) -> List[Signal]:
        """Calculate executable signals from a quotes dictionary."""
        signals: List[Signal] = []
        for symbol, quote in quotes_dict.items():
            price = self._extract_price(quote)
            if price is None or price <= 0:
                continue

            action = self.calculate_signal(symbol, price)
            if action == "HOLD":
                continue

            if not self.emit_repeated_signals and self.last_actions.get(symbol) == action:
                continue
            self.last_actions[symbol] = action

            signals.append(
                Signal(
                    symbol=symbol,
                    action=action,
                    price=price,
                    quantity=self._calculate_quantity(price) if action == "BUY" else 0,
                    reason=f"{self.name}: MA{self.fast_period}/MA{self.slow_period} {action}",
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

        return signals

    def _calculate_quantity(self, price: float) -> int:
        cash_to_use = self.initial_capital * self.trade_pct
        quantity = int(cash_to_use / price / self.lot_size) * self.lot_size
        return max(0, quantity)

    def _extract_price(self, quote) -> Optional[float]:
        if isinstance(quote, dict):
            value = quote.get("price")
        else:
            value = getattr(quote, "price", None)

        try:
            return float(value)
        except (TypeError, ValueError):
            return None
