"""Independent take-profit / stop-loss monitor."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class TriggerType(str, Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"


@dataclass
class TriggerResult:
    symbol: str
    trigger_type: TriggerType
    trigger_price: float
    current_price: float
    position_quantity: float
    should_close: bool = True
    reason: str = ""


@dataclass
class MonitorConfig:
    check_interval_seconds: float = 5.0
    sl_enabled: bool = True
    tp_enabled: bool = True
    trailing_stop_enabled: bool = False
    trailing_stop_distance_pct: float = 0.02


@dataclass
class MonitoredPosition:
    symbol: str
    quantity: float
    entry_price: float
    sl_price: float | None = None
    tp_price: float | None = None
    position_id: str = ""
    highest_price: float = 0.0
    lowest_price: float = 0.0
    direction: str = "long"
    registered_at: str = ""


class TakeProfitManager:
    """Monitor open positions independently from strategy signal generation."""

    def __init__(self, market_provider: Any, config: MonitorConfig | None = None):
        self.provider = market_provider
        self.config = config or MonitorConfig()
        self._positions: dict[str, MonitoredPosition] = {}
        self._on_trigger: Callable[[TriggerResult], None] | None = None
        self._trigger_log: list[TriggerResult] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def register_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        sl_price: float | None = None,
        tp_price: float | None = None,
        position_id: str = "",
        direction: str = "long",
    ) -> None:
        self._positions[symbol] = MonitoredPosition(
            symbol=symbol,
            quantity=float(quantity or 0),
            entry_price=float(entry_price or 0),
            sl_price=sl_price,
            tp_price=tp_price,
            position_id=position_id,
            highest_price=float(entry_price or 0),
            lowest_price=float(entry_price or 0),
            direction=str(direction or "long"),
            registered_at=datetime.now(timezone.utc).isoformat(),
        )

    def unregister_position(self, symbol: str) -> None:
        self._positions.pop(symbol, None)

    def set_trigger_callback(self, callback: Callable[[TriggerResult], None]) -> None:
        self._on_trigger = callback

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def check_once(self) -> list[TriggerResult]:
        results: list[TriggerResult] = []
        for symbol, position in list(self._positions.items()):
            price = self._latest_price(symbol)
            if price <= 0:
                continue
            position.highest_price = max(position.highest_price, price)
            position.lowest_price = min(position.lowest_price, price)
            result = self._check_position(position, price)
            if result:
                results.append(result)

        for result in results:
            self._trigger_log.append(result)
            self.unregister_position(result.symbol)
            if self._on_trigger is not None:
                self._on_trigger(result)
        return results

    def get_trigger_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "symbol": item.symbol,
                "type": item.trigger_type.value,
                "trigger_price": item.trigger_price,
                "current_price": item.current_price,
                "quantity": item.position_quantity,
                "reason": item.reason,
            }
            for item in self._trigger_log[-max(1, int(limit or 100)) :]
        ]

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            finally:
                self._stop_event.wait(timeout=max(float(self.config.check_interval_seconds or 5), 0.1))

    def _check_position(self, position: MonitoredPosition, price: float) -> TriggerResult | None:
        long_side = position.direction != "short"
        if self.config.sl_enabled and position.sl_price:
            if (long_side and price <= position.sl_price) or (not long_side and price >= position.sl_price):
                return TriggerResult(position.symbol, TriggerType.STOP_LOSS, position.sl_price, price, position.quantity, True, "stop loss triggered")
        if self.config.tp_enabled and position.tp_price:
            if (long_side and price >= position.tp_price) or (not long_side and price <= position.tp_price):
                return TriggerResult(position.symbol, TriggerType.TAKE_PROFIT, position.tp_price, price, position.quantity, True, "take profit triggered")
        if self.config.trailing_stop_enabled:
            if long_side:
                trail = position.highest_price * (1 - self.config.trailing_stop_distance_pct)
                if price <= trail:
                    return TriggerResult(position.symbol, TriggerType.TRAILING_STOP, trail, price, position.quantity, True, "trailing stop triggered")
            else:
                trail = position.lowest_price * (1 + self.config.trailing_stop_distance_pct)
                if price >= trail:
                    return TriggerResult(position.symbol, TriggerType.TRAILING_STOP, trail, price, position.quantity, True, "trailing stop triggered")
        return None

    def _latest_price(self, symbol: str) -> float:
        quotes = self.provider.fetch_quotes([symbol])
        if not quotes:
            return 0.0
        try:
            return float(quotes[0].get("price", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
