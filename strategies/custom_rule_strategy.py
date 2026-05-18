"""Config-driven custom rule strategy."""

from datetime import datetime
from typing import Dict, List, Optional

from .base_strategy import BaseStrategy, TradeSignal


class CustomRuleStrategy(BaseStrategy):
    """Simple editable strategy backed by threshold rules in YAML/API config."""

    def __init__(self, config: Dict):
        super().__init__(config.get("name", "Custom Rule Strategy"), config)
        self.buy_below = self._optional_float(config.get("buy_below"))
        self.sell_above = self._optional_float(config.get("sell_above"))
        self.position_ratio = float(config.get("position_ratio", 0.1))
        self.initial_capital = float(config.get("initial_capital", self.initial_capital))
        self.last_signal: Dict[str, str] = {}

        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def calculate_signals(self, quotes: Dict[str, Dict]) -> List[TradeSignal]:
        signals: List[TradeSignal] = []
        if not self.enabled:
            return signals

        for symbol, quote in quotes.items():
            if self.symbols and symbol not in self.symbols:
                continue
            price = self._extract_price(quote)
            if price <= 0:
                continue

            self._ensure_symbol_state(symbol)
            signal = self._build_signal(symbol, price)
            if signal and signal.action != self.last_signal.get(symbol, "HOLD"):
                signals.append(signal)
                self.signal_history.append(signal)
                self.last_signal[symbol] = signal.action

        return signals

    def update_config(self, new_config: Dict) -> None:
        super().update_config(new_config)
        if "buy_below" in new_config:
            self.buy_below = self._optional_float(new_config.get("buy_below"))
        if "sell_above" in new_config:
            self.sell_above = self._optional_float(new_config.get("sell_above"))
        if "position_ratio" in new_config:
            self.position_ratio = float(new_config["position_ratio"])
        if "initial_capital" in new_config:
            self.initial_capital = float(new_config["initial_capital"])

    def get_strategy_status(self, symbol: str) -> Dict:
        return {
            "symbol": symbol,
            "buy_below": self.buy_below,
            "sell_above": self.sell_above,
            "last_signal": self.last_signal.get(symbol, "HOLD"),
            "position": self.get_current_position(symbol),
        }

    def _build_signal(self, symbol: str, price: float) -> Optional[TradeSignal]:
        if self.buy_below is not None and price <= self.buy_below:
            quantity = self._calculate_quantity(symbol, price, "BUY")
            if quantity > 0:
                return TradeSignal(
                    symbol=symbol,
                    action="BUY",
                    price=price,
                    quantity=quantity,
                    reason=f"custom_rule: price <= {self.buy_below}",
                    timestamp=datetime.now(),
                    confidence=0.6,
                )

        if self.sell_above is not None and price >= self.sell_above and self.get_current_position(symbol) > 0:
            quantity = self._calculate_quantity(symbol, price, "SELL")
            if quantity > 0:
                return TradeSignal(
                    symbol=symbol,
                    action="SELL",
                    price=price,
                    quantity=quantity,
                    reason=f"custom_rule: price >= {self.sell_above}",
                    timestamp=datetime.now(),
                    confidence=0.6,
                )

        return None

    def _calculate_quantity(self, symbol: str, price: float, action: str) -> float:
        if action == "SELL":
            return float(self.get_current_position(symbol))
        if price <= 0:
            return 0.0
        quantity = (self.initial_capital * self.position_ratio) / price
        return max(0.0001, quantity) if quantity > 0 else 0.0

    def _ensure_symbol_state(self, symbol: str) -> None:
        self.last_signal.setdefault(symbol, "HOLD")

    def _extract_price(self, quote) -> float:
        if isinstance(quote, dict):
            value = quote.get("price")
        else:
            value = getattr(quote, "price", None)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _optional_float(self, value) -> Optional[float]:
        if value in {None, ""}:
            return None
        return float(value)
