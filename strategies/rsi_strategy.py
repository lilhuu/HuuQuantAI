"""RSI strategy implementation for realtime quotes and historical bars."""

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from .base_strategy import BaseStrategy, TradeSignal


class RSIStrategy(BaseStrategy):
    """Relative Strength Index strategy."""

    def __init__(self, config: Dict):
        super().__init__(config.get("name", "RSI Strategy"), config)
        self.period = int(config.get("rsi_period", config.get("period", 14)))
        self.overbought = float(config.get("overbought", 70))
        self.oversold = float(config.get("oversold", 30))
        self.position_ratio = float(config.get("position_ratio", 0.1))
        self.initial_capital = float(config.get("initial_capital", 100000))
        self._realtime_history: Dict[str, pd.DataFrame] = {}
        self.last_signal: Dict[str, str] = {}

        if self.period <= 0:
            raise ValueError("rsi_period must be positive")
        if not 0 <= self.oversold < self.overbought <= 100:
            raise ValueError("RSI thresholds must satisfy 0 <= oversold < overbought <= 100")

        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def calculate_signals(self, data: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        signals: List[TradeSignal] = []
        if not self.enabled:
            return signals

        for symbol, raw_data in data.items():
            if self.symbols and symbol not in self.symbols:
                continue

            df = self._as_dataframe(symbol, raw_data)
            if len(df) < self.period + 1 or "close" not in df.columns:
                continue

            prices = df["close"].astype(float)
            rsi = self._calculate_rsi(prices)
            current_price = float(prices.iloc[-1])

            signal: Optional[TradeSignal] = None
            if rsi < self.oversold:
                signal = TradeSignal(
                    symbol=symbol,
                    action="BUY",
                    price=current_price,
                    quantity=self._calculate_quantity(symbol, current_price, "BUY"),
                    reason=f"RSI oversold: {rsi:.2f}",
                    timestamp=datetime.now(),
                    confidence=self._calculate_confidence(rsi),
                )
            elif rsi > self.overbought and self.get_current_position(symbol) > 0:
                signal = TradeSignal(
                    symbol=symbol,
                    action="SELL",
                    price=current_price,
                    quantity=self._calculate_quantity(symbol, current_price, "SELL"),
                    reason=f"RSI overbought: {rsi:.2f}",
                    timestamp=datetime.now(),
                    confidence=self._calculate_confidence(rsi),
                )

            if signal and signal.action != self.last_signal.get(symbol, "HOLD"):
                signals.append(signal)
                self.signal_history.append(signal)
                self.last_signal[symbol] = signal.action

        return signals

    def get_strategy_status(self, symbol: str) -> Dict:
        if symbol not in self._realtime_history:
            return {}

        df = self._realtime_history[symbol]
        if len(df) < self.period + 1 or "close" not in df.columns:
            return {}

        prices = df["close"].astype(float)
        rsi = self._calculate_rsi(prices)
        return {
            "symbol": symbol,
            "current_price": float(prices.iloc[-1]),
            "rsi": float(rsi),
            "rsi_period": self.period,
            "overbought": self.overbought,
            "oversold": self.oversold,
            "last_signal": self.last_signal.get(symbol, "HOLD"),
            "position": self.get_current_position(symbol),
        }

    def update_config(self, new_config: Dict) -> None:
        super().update_config(new_config)
        if "rsi_period" in new_config or "period" in new_config:
            self.period = int(new_config.get("rsi_period", new_config.get("period", self.period)))
        if "overbought" in new_config:
            self.overbought = float(new_config["overbought"])
        if "oversold" in new_config:
            self.oversold = float(new_config["oversold"])
        if "position_ratio" in new_config:
            self.position_ratio = float(new_config["position_ratio"])
        if "initial_capital" in new_config:
            self.initial_capital = float(new_config["initial_capital"])

        if self.period <= 0:
            raise ValueError("rsi_period must be positive")
        if not 0 <= self.oversold < self.overbought <= 100:
            raise ValueError("RSI thresholds must satisfy 0 <= oversold < overbought <= 100")

        for symbol in self.symbols:
            self._ensure_symbol_state(symbol)

    def _calculate_quantity(self, symbol: str, price: float, action: str) -> float:
        if action == "SELL":
            return float(self.get_current_position(symbol))

        if price <= 0:
            return 0.0
        capital_per_trade = self.initial_capital * self.position_ratio
        quantity = capital_per_trade / price
        return max(0.0001, min(quantity, 10000.0)) if quantity > 0 else 0.0

    def _calculate_rsi(self, prices: pd.Series) -> float:
        delta = prices.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.rolling(self.period).mean().iloc[-1]
        avg_loss = losses.rolling(self.period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _calculate_confidence(self, rsi: float) -> float:
        if rsi < self.oversold:
            distance = (self.oversold - rsi) / max(self.oversold, 1)
        elif rsi > self.overbought:
            distance = (rsi - self.overbought) / max(100 - self.overbought, 1)
        else:
            distance = 0
        return max(0.3, min(1.0, distance + 0.3))

    def _as_dataframe(self, symbol: str, raw_data) -> pd.DataFrame:
        self._ensure_symbol_state(symbol)

        if isinstance(raw_data, pd.DataFrame):
            return raw_data

        if isinstance(raw_data, dict) and "price" in raw_data:
            row = pd.DataFrame(
                [
                    {
                        "date": raw_data.get("timestamp", datetime.now()),
                        "close": raw_data["price"],
                    }
                ]
            )
            history = self._realtime_history.get(symbol, pd.DataFrame())
            history = pd.concat([history, row], ignore_index=True).tail(self.period + 5)
            self._realtime_history[symbol] = history
            return history

        return pd.DataFrame()

    def _ensure_symbol_state(self, symbol: str) -> None:
        if symbol not in self._realtime_history:
            self._realtime_history[symbol] = pd.DataFrame()
        if symbol not in self.last_signal:
            self.last_signal[symbol] = "HOLD"
