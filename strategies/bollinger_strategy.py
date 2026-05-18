"""Bollinger Bands mean-reversion strategy."""

from __future__ import annotations

from datetime import datetime
from statistics import fmean, pstdev
from typing import Dict, List

from .base_strategy import BaseStrategy, TradeSignal


class BollingerBandsStrategy(BaseStrategy):
    """Buy near the lower band and sell near the upper band."""

    def __init__(self, config: Dict):
        super().__init__(config.get("name", "Bollinger Bands"), config)
        self.period = int(config.get("period", config.get("bb_period", 20)))
        self.stddev_multiplier = float(config.get("stddev_multiplier", config.get("bb_stddev", 2.0)))
        self.position_ratio = float(config.get("position_ratio", 0.1))
        self.price_history: Dict[str, list[float]] = {}
        self.last_signal: Dict[str, str] = {}

        if self.period < 2:
            raise ValueError("bollinger period must be at least 2")
        if self.stddev_multiplier <= 0:
            raise ValueError("stddev_multiplier must be positive")

        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def calculate_signals(self, quotes: Dict[str, Dict]) -> List[TradeSignal]:
        signals: list[TradeSignal] = []
        if not self.enabled:
            return signals

        for symbol, quote in quotes.items():
            if self.symbols and symbol not in self.symbols:
                continue

            price = self._extract_price(quote)
            if price <= 0:
                continue

            self._ensure_symbol_state(symbol)
            history = self.price_history[symbol]
            history.append(price)
            if len(history) > self.period * 3:
                del history[:-self.period * 3]
            if len(history) < self.period:
                continue

            window = history[-self.period:]
            middle = float(fmean(window))
            deviation = float(pstdev(window))
            upper = middle + self.stddev_multiplier * deviation
            lower = middle - self.stddev_multiplier * deviation
            if deviation <= 0:
                continue

            action = None
            reason = ""
            if price <= lower:
                action = "BUY"
                reason = f"price below lower Bollinger band: {price:.2f} <= {lower:.2f}"
            elif price >= upper and self.get_current_position(symbol) > 0:
                action = "SELL"
                reason = f"price above upper Bollinger band: {price:.2f} >= {upper:.2f}"

            if not action or action == self.last_signal.get(symbol, "HOLD"):
                continue

            quantity = self._calculate_quantity(symbol, price, action)
            if quantity <= 0:
                continue

            signal = TradeSignal(
                symbol=symbol,
                action=action,
                price=price,
                quantity=quantity,
                reason=reason,
                timestamp=datetime.now(),
                confidence=self._confidence(price, middle, upper, lower),
            )
            signals.append(signal)
            self.signal_history.append(signal)
            self.last_signal[symbol] = action

        return signals

    def update_config(self, new_config: Dict) -> None:
        super().update_config(new_config)
        if "period" in new_config or "bb_period" in new_config:
            self.period = int(new_config.get("period", new_config.get("bb_period", self.period)))
        if "stddev_multiplier" in new_config or "bb_stddev" in new_config:
            self.stddev_multiplier = float(
                new_config.get("stddev_multiplier", new_config.get("bb_stddev", self.stddev_multiplier))
            )
        if "position_ratio" in new_config:
            self.position_ratio = float(new_config["position_ratio"])
        if "initial_capital" in new_config:
            self.initial_capital = float(new_config["initial_capital"])
        if self.period < 2:
            raise ValueError("bollinger period must be at least 2")
        if self.stddev_multiplier <= 0:
            raise ValueError("stddev_multiplier must be positive")
        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def _calculate_quantity(self, symbol: str, price: float, action: str) -> float:
        if action == "SELL":
            return float(self.get_current_position(symbol))
        if price <= 0:
            return 0.0
        capital = float(self.config.get("initial_capital", self.initial_capital) or self.initial_capital)
        quantity = capital * self.position_ratio / price
        return max(0.0001, quantity) if quantity > 0 else 0.0

    def _confidence(self, price: float, middle: float, upper: float, lower: float) -> float:
        band_width = max(upper - lower, 0.01)
        distance = abs(price - middle) / band_width
        return max(0.3, min(1.0, distance * 2))

    def _ensure_symbol_state(self, symbol: str) -> None:
        self.price_history.setdefault(symbol, [])
        self.last_signal.setdefault(symbol, "HOLD")

    def _extract_price(self, quote) -> float:
        value = quote.get("price", quote.get("close", 0)) if isinstance(quote, dict) else getattr(quote, "price", 0)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
