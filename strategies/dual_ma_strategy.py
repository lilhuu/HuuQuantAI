"""双均线策略 - 快慢均线交叉交易。"""

from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .base_strategy import BaseStrategy, TradeSignal


class DualMAStrategy(BaseStrategy):
    """双均线交叉策略。"""

    def __init__(self, config: Dict):
        super().__init__(config.get("name", "双均线策略"), config)

        self.fast_period = config.get("fast_period", 5)
        self.slow_period = config.get("slow_period", 20)
        self.position_ratio = config.get("position_ratio", 0.1)

        if self.fast_period <= 0 or self.slow_period <= 0:
            raise ValueError("fast_period and slow_period must be positive")
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be smaller than slow_period")

        self.price_history = {}
        self.ma_history = {}
        self.last_signal = {}

        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def calculate_signals(self, quotes: Dict[str, Dict]) -> List[TradeSignal]:
        """计算双均线交易信号。"""
        signals = []
        if not self.enabled:
            return signals

        for symbol, quote in quotes.items():
            if self.symbols and symbol not in self.symbols:
                continue

            current_price = self._extract_price(quote)
            if current_price <= 0:
                continue

            self._ensure_symbol_state(symbol)
            self.price_history[symbol].append(current_price)

            max_history = self.slow_period * 2
            if len(self.price_history[symbol]) > max_history:
                self.price_history[symbol] = self.price_history[symbol][-max_history:]

            if len(self.price_history[symbol]) < self.slow_period:
                continue

            prices = np.array(self.price_history[symbol], dtype=float)
            fast_ma = float(np.mean(prices[-self.fast_period:]))
            slow_ma = float(np.mean(prices[-self.slow_period:]))

            self.ma_history[symbol]["fast"].append(fast_ma)
            self.ma_history[symbol]["slow"].append(slow_ma)

            if len(self.ma_history[symbol]["fast"]) > 10:
                self.ma_history[symbol]["fast"] = self.ma_history[symbol]["fast"][-10:]
                self.ma_history[symbol]["slow"] = self.ma_history[symbol]["slow"][-10:]

            signal = self._generate_signal(symbol, fast_ma, slow_ma, current_price)
            if signal:
                signals.append(signal)
                self.signal_history.append(signal)
                self.last_signal[symbol] = signal.action

        return signals

    def _generate_signal(
        self,
        symbol: str,
        fast_ma: float,
        slow_ma: float,
        current_price: float,
    ) -> Optional[TradeSignal]:
        """生成具体交易信号。"""
        if len(self.ma_history[symbol]["fast"]) < 2:
            return None

        prev_fast = self.ma_history[symbol]["fast"][-2]
        prev_slow = self.ma_history[symbol]["slow"][-2]

        action = "HOLD"
        reason = ""

        if prev_fast <= prev_slow and fast_ma > slow_ma:
            action = "BUY"
            reason = f"MA金叉: {self.fast_period}日线上穿{self.slow_period}日线"
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            action = "SELL"
            reason = f"MA死叉: {self.fast_period}日线下穿{self.slow_period}日线"

        if action == "HOLD" or action == self.last_signal.get(symbol, "HOLD"):
            return None

        quantity = self._calculate_quantity(symbol, current_price, action)
        if quantity <= 0:
            return None

        return TradeSignal(
            symbol=symbol,
            action=action,
            price=current_price,
            quantity=quantity,
            reason=reason,
            timestamp=datetime.now(),
            confidence=self._calculate_confidence(fast_ma, slow_ma),
        )

    def _calculate_quantity(self, symbol: str, price: float, action: str) -> float:
        """计算交易数量（加密货币小数精度）。"""
        if action == "BUY":
            capital = self.config.get("initial_capital", 100000)
            position_value = capital * self.position_ratio
            quantity = position_value / price
            return max(0.0001, quantity) if quantity > 0 else 0.0

        if action == "SELL":
            return float(self.get_current_position(symbol))

        return 0.0

    def _calculate_confidence(self, fast_ma: float, slow_ma: float) -> float:
        """计算信号置信度。"""
        if slow_ma <= 0:
            return 0.3
        diff_percent = abs(fast_ma - slow_ma) / slow_ma
        confidence = min(diff_percent * 10, 1.0)
        return max(0.3, confidence)

    def get_strategy_status(self, symbol: str) -> Dict:
        """获取策略状态。"""
        if symbol not in self.price_history:
            return {}

        prices = self.price_history[symbol]
        if len(prices) < self.slow_period:
            return {}

        fast_ma = float(np.mean(prices[-self.fast_period:]))
        slow_ma = float(np.mean(prices[-self.slow_period:]))

        return {
            "symbol": symbol,
            "current_price": prices[-1] if prices else 0,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "ma_diff": fast_ma - slow_ma,
            "ma_diff_percent": (fast_ma - slow_ma) / slow_ma * 100 if slow_ma else 0,
            "last_signal": self.last_signal.get(symbol, "HOLD"),
            "position": self.get_current_position(symbol),
        }

    def _ensure_symbol_state(self, symbol: str) -> None:
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        if symbol not in self.ma_history:
            self.ma_history[symbol] = {"fast": [], "slow": []}
        if symbol not in self.last_signal:
            self.last_signal[symbol] = "HOLD"

    def _extract_price(self, quote) -> float:
        if isinstance(quote, dict):
            value = quote.get("price", 0)
        else:
            value = getattr(quote, "price", 0)

        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
