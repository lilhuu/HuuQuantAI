"""策略基类 — 所有交易策略的基类（加密货币小数精度）。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import math
import statistics
from typing import Dict, List, Optional, Union


@dataclass
class TradeSignal:
    """交易信号 — 支持加密货币小数精度。"""

    symbol: str
    action: str
    price: float
    quantity: float
    reason: str
    timestamp: Optional[datetime] = None
    confidence: float = 1.0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        self.action = self.action.upper()


# Backward-compatible alias used by older modules and tests.
Signal = TradeSignal


class BaseStrategy(ABC):
    """策略基类。"""

    def __init__(self, name: Union[str, Dict], config: Optional[Dict] = None):
        if config is None and isinstance(name, dict):
            config = name
            name = config.get("name", self.__class__.__name__)

        self.name = str(name)
        self.config = config or {}
        self.symbols = self.config.get("symbols", [])
        self.enabled = self.config.get("enabled", True)
        self.initial_capital = float(self.config.get("initial_capital", 100000) or 100000)

        self.position_history = {}
        self.signal_history: List[TradeSignal] = []
        self._cash = self.initial_capital
        self._positions: Dict[str, Dict[str, float]] = {}
        self._trade_returns: List[float] = []
        self._realized_pnl = 0.0
        self._equity_curve: List[Dict[str, Union[datetime, float]]] = [
            {"timestamp": datetime.now(), "equity": self.initial_capital}
        ]

    @abstractmethod
    def calculate_signals(self, quotes: Dict[str, Dict]) -> List[TradeSignal]:
        """计算交易信号 - 子类必须实现。"""
        raise NotImplementedError

    def on_bar(self, bar_data: Dict[str, Dict]) -> List[TradeSignal]:
        """兼容旧策略引擎的K线回调名称。"""
        return self.calculate_signals(bar_data)

    def update_config(self, new_config: Dict) -> None:
        """更新配置。"""
        self.config.update(new_config)
        if "symbols" in new_config:
            self.symbols = new_config["symbols"]
        if "enabled" in new_config:
            self.enabled = new_config["enabled"]

    def add_position_record(
        self,
        symbol: str,
        action: str,
        price: float,
        quantity: float,
    ) -> None:
        """记录持仓变化（加密小数精度）。"""
        if symbol not in self.position_history:
            self.position_history[symbol] = []

        self.position_history[symbol].append(
            {
                "action": action.upper(),
                "price": price,
                "quantity": quantity,
                "timestamp": datetime.now(),
            }
        )
        self._record_trade_metrics(symbol, action, price, quantity)

    def get_current_position(self, symbol: str) -> float:
        """获取当前持仓数量（小数精度）。"""
        if symbol not in self.position_history:
            return 0.0

        position = 0.0
        for record in self.position_history[symbol]:
            if record["action"] == "BUY":
                position += record["quantity"]
            elif record["action"] == "SELL":
                position -= record["quantity"]

        return max(0.0, position)

    def get_performance_stats(self) -> Dict:
        """获取策略绩效统计。"""
        total_trades = sum(len(records) for records in self.position_history.values())
        buy_trades = sum(
            1
            for records in self.position_history.values()
            for record in records
            if record["action"] == "BUY"
        )
        sell_trades = total_trades - buy_trades

        performance = self._calculate_performance_metrics()
        return {
            "strategy_name": self.name,
            "enabled": self.enabled,
            "total_trades": total_trades,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "active_symbols": len(self.position_history),
            "signal_count": len(self.signal_history),
            **performance,
        }

    def reset_performance(self) -> None:
        """Reset derived performance state without changing strategy parameters."""
        self.position_history = {}
        self.signal_history = []
        self._cash = self.initial_capital
        self._positions = {}
        self._trade_returns = []
        self._realized_pnl = 0.0
        self._equity_curve = [{"timestamp": datetime.now(), "equity": self.initial_capital}]

    def _record_trade_metrics(self, symbol: str, action: str, price: float, quantity: float) -> None:
        action = str(action or "").upper()
        price = float(price or 0)
        quantity = float(quantity or 0)
        if price <= 0 or quantity <= 0:
            return

        position = self._positions.setdefault(symbol, {"quantity": 0.0, "avg_price": 0.0, "last_price": price})
        position["last_price"] = price

        if action == "BUY":
            current_quantity = float(position["quantity"])
            new_quantity = current_quantity + quantity
            old_cost = current_quantity * float(position["avg_price"])
            new_cost = quantity * price
            position["quantity"] = new_quantity
            position["avg_price"] = (old_cost + new_cost) / new_quantity if new_quantity else 0.0
            self._cash -= new_cost
        elif action == "SELL":
            sell_quantity = min(quantity, float(position["quantity"]))
            if sell_quantity <= 0:
                return
            realized = (price - float(position["avg_price"])) * sell_quantity
            cost_basis = float(position["avg_price"]) * sell_quantity
            position["quantity"] -= sell_quantity
            self._cash += sell_quantity * price
            self._realized_pnl += realized
            if cost_basis > 0:
                self._trade_returns.append(realized / cost_basis)
            if float(position["quantity"]) <= 0:
                position["quantity"] = 0.0
                position["avg_price"] = 0.0

        self._equity_curve.append({"timestamp": datetime.now(), "equity": self._current_equity()})

    def _current_equity(self) -> float:
        equity = self._cash
        for position in self._positions.values():
            equity += float(position.get("quantity", 0)) * float(position.get("last_price", 0))
        return float(equity)

    def _calculate_performance_metrics(self) -> Dict[str, float]:
        equity_values = [float(item["equity"]) for item in self._equity_curve if float(item["equity"]) > 0]
        current_equity = equity_values[-1] if equity_values else self.initial_capital
        total_return = (
            (current_equity - self.initial_capital) / self.initial_capital
            if self.initial_capital
            else 0.0
        )
        max_drawdown = self._max_drawdown(equity_values)
        sharpe_ratio = self._risk_adjusted_ratio(self._trade_returns)
        information_ratio = self._risk_adjusted_ratio(self._trade_returns, benchmark=0.0)
        calmar_ratio = (total_return / max_drawdown) if max_drawdown > 0 else 0.0

        return {
            "initial_capital": float(self.initial_capital),
            "current_equity": float(current_equity),
            "total_return": float(total_return),
            "realized_pnl": float(self._realized_pnl),
            "max_drawdown": float(max_drawdown),
            "sharpe_ratio": float(sharpe_ratio),
            "calmar_ratio": float(calmar_ratio),
            "information_ratio": float(information_ratio),
        }

    def _max_drawdown(self, equity_values: List[float]) -> float:
        if not equity_values:
            return 0.0
        peak = equity_values[0]
        max_drawdown = 0.0
        for equity in equity_values:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        return max_drawdown

    def _risk_adjusted_ratio(self, returns: List[float], benchmark: float = 0.0) -> float:
        if not returns:
            return 0.0
        excess_returns = [float(item) - benchmark for item in returns]
        mean_return = statistics.fmean(excess_returns)
        if len(excess_returns) < 2:
            return 0.0
        volatility = statistics.pstdev(excess_returns)
        if volatility <= 0:
            return 0.0
        return (mean_return / volatility) * math.sqrt(252)
