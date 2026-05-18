"""Price momentum breakout strategy."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from .base_strategy import BaseStrategy, TradeSignal


class MomentumStrategy(BaseStrategy):
    """Trade when lookback return crosses configured thresholds."""

    def __init__(self, config: Dict):
        super().__init__(config.get("name", "Momentum"), config)
        self.lookback_period = int(config.get("lookback_period", config.get("period", 10)))
        self.buy_threshold = float(config.get("buy_threshold", 0.03))
        self.sell_threshold = float(config.get("sell_threshold", -0.02))
        self.position_ratio = float(config.get("position_ratio", 0.1))
        self.price_history: Dict[str, list[float]] = {}
        self.last_signal: Dict[str, str] = {}

        if self.lookback_period < 1:
            raise ValueError("lookback_period must be positive")

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
            if len(history) > self.lookback_period * 4:
                del history[:-self.lookback_period * 4]
            if len(history) <= self.lookback_period:
                continue

            base_price = history[-self.lookback_period - 1]
            if base_price <= 0:
                continue
            momentum = (price - base_price) / base_price

            action = None
            if momentum >= self.buy_threshold:
                action = "BUY"
            elif momentum <= self.sell_threshold and self.get_current_position(symbol) > 0:
                action = "SELL"

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
                reason=f"{self.lookback_period}-bar momentum {momentum:.2%}",
                timestamp=datetime.now(),
                confidence=max(0.3, min(1.0, abs(momentum) / max(abs(self.buy_threshold), abs(self.sell_threshold), 0.01))),
            )
            signals.append(signal)
            self.signal_history.append(signal)
            self.last_signal[symbol] = action

        return signals

    def update_config(self, new_config: Dict) -> None:
        super().update_config(new_config)
        if "lookback_period" in new_config or "period" in new_config:
            self.lookback_period = int(new_config.get("lookback_period", new_config.get("period", self.lookback_period)))
        if "buy_threshold" in new_config:
            self.buy_threshold = float(new_config["buy_threshold"])
        if "sell_threshold" in new_config:
            self.sell_threshold = float(new_config["sell_threshold"])
        if "position_ratio" in new_config:
            self.position_ratio = float(new_config["position_ratio"])
        if "initial_capital" in new_config:
            self.initial_capital = float(new_config["initial_capital"])
        if self.lookback_period < 1:
            raise ValueError("lookback_period must be positive")
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

    def _ensure_symbol_state(self, symbol: str) -> None:
        self.price_history.setdefault(symbol, [])
        self.last_signal.setdefault(symbol, "HOLD")

    def _extract_price(self, quote) -> float:
        value = quote.get("price", quote.get("close", 0)) if isinstance(quote, dict) else getattr(quote, "price", 0)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
