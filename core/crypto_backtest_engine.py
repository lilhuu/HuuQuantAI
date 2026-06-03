"""Crypto-only backtest engine.

The engine is intentionally isolated from the paper broker. It consumes
strategy signals, simulates fills with USDT cash, and never places orders.
"""

from __future__ import annotations

from math import sqrt
from statistics import fmean, pstdev
from typing import Any

from core.backtest_validation import categorize_no_entry_reason, create_backtest_diagnostics
from core.crypto_strategy_engine import BUILTIN_STRATEGIES, CryptoStrategyEngine, StrategyConfig
from core.risk_budget import RiskBudgetConfig, RiskBudgetSizer


PERIODS_PER_YEAR: dict[str, int] = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


class CryptoBacktestEngine:
    """Run decimal, USDT-denominated crypto strategy simulations."""

    def __init__(
        self,
        *,
        initial_cash: float = 10000.0,
        quote_currency: str = "USDT",
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        min_quantity: float = 0.000001,
        position_sizing: str = "strategy_position_ratio",
        period: str = "1h",
    ) -> None:
        self.initial_cash = max(float(initial_cash or 0), 1.0)
        self.quote_currency = str(quote_currency or "USDT").upper()
        self.fee_rate = max(float(fee_rate or 0), 0.0)
        self.slippage_rate = max(float(slippage_rate or 0), 0.0)
        self.min_quantity = max(float(min_quantity or 0), 0.000001)
        self.position_sizing = str(position_sizing or "strategy_position_ratio")
        self.period = str(period or "1h")
        self.strategy_engine = CryptoStrategyEngine()
        self.risk_sizer = RiskBudgetSizer()

    def run_many(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        configs: list[StrategyConfig],
    ) -> list[dict[str, Any]]:
        return [self.run(market_data, config) for config in configs]

    def run(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        config: StrategyConfig,
    ) -> dict[str, Any]:
        if not config.enabled:
            return self._empty_result(config, "strategy disabled")

        max_len = max((len(market_data.get(symbol, [])) for symbol in config.symbols), default=0)
        if max_len <= 0:
            return self._empty_result(config, "insufficient market data")

        cash = self.initial_cash
        positions: dict[str, dict[str, float]] = {}
        last_prices: dict[str, float] = {}
        trades: list[dict[str, Any]] = []
        signal_count = 0
        equity_curve: list[dict[str, Any]] = []
        no_entry_counts: dict[str, int] = {}

        for index in range(max_len):
            timestamp = ""
            for symbol in config.symbols:
                candles = market_data.get(symbol, [])
                if index >= len(candles):
                    continue
                history_window = candles[: index + 1]
                current = history_window[-1]
                timestamp = timestamp or self._timestamp(current, index)
                price = self._float(current.get("close", current.get("price")))
                if price <= 0:
                    continue
                last_prices[symbol] = price
                position = positions.setdefault(symbol, {"quantity": 0.0, "avg_price": 0.0})
                intrabar_trade = self._maybe_exit_intrabar(config, symbol, current, cash, position, index, timestamp)
                if intrabar_trade:
                    cash = float(intrabar_trade["cash_after"])
                    trades.append(intrabar_trade)
                    continue

                signal_window = self._strategy_window(config, candles, index)
                signal = self.strategy_engine.evaluate_strategy(config, symbol, signal_window)
                if not signal or signal.action == "HOLD":
                    reason = signal.reason if signal else "insufficient indicators or no signal"
                    category = categorize_no_entry_reason(config.type, reason)
                    no_entry_counts[category] = no_entry_counts.get(category, 0) + 1
                    continue
                signal_count += 1
                if signal.action == "BUY":
                    current_risk = self.risk_sizer.calculate_total_risk(list(positions.values()))
                    equity = cash + self._market_value(positions, last_prices)
                    trade = self._buy(config, symbol, price, cash, position, index, timestamp, signal.reason, history_window, equity, current_risk)
                    if trade:
                        cash = float(trade["cash_after"])
                        trades.append(trade)
                elif signal.action == "SELL":
                    trade = self._sell(config, symbol, price, cash, position, index, timestamp, signal.reason)
                    if trade:
                        cash = float(trade["cash_after"])
                        trades.append(trade)

            market_value = self._market_value(positions, last_prices)
            equity_curve.append(
                {
                    "index": index,
                    "timestamp": timestamp or str(index),
                    "cash": cash,
                    "market_value": market_value,
                    "equity": cash + market_value,
                }
            )

        drawdown_curve = self._drawdown_curve(equity_curve)
        metrics = self._metrics(equity_curve, drawdown_curve, trades)
        final_equity = metrics["final_equity"]
        diagnostics = self._diagnostics(trades, no_entry_counts)
        return {
            "strategy_id": config.strategy_id,
            "strategy_name": BUILTIN_STRATEGIES[config.type]["name"],
            "strategy_type": config.type,
            "symbols": config.symbols,
            "quote_currency": self.quote_currency,
            "period": self.period,
            "initial_cash": self.initial_cash,
            "final_equity": final_equity,
            "total_return_percent": metrics["total_return_percent"],
            "max_drawdown_percent": metrics["max_drawdown_percent"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "calmar_ratio": metrics["calmar_ratio"],
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
            "avg_win": metrics["avg_win"],
            "avg_loss": metrics["avg_loss"],
            "gross_profit": metrics["gross_profit"],
            "gross_loss": metrics["gross_loss"],
            "signal_count": signal_count,
            "trade_count": len(trades),
            "trades": trades,
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "min_quantity": self.min_quantity,
            "position_sizing": self.position_sizing,
            "diagnostics": diagnostics,
            "message": "ok",
        }

    def _buy(
        self,
        config: StrategyConfig,
        symbol: str,
        price: float,
        cash: float,
        position: dict[str, float],
        index: int,
        timestamp: str,
        reason: str,
        candles: list[dict[str, Any]] | None = None,
        account_equity: float | None = None,
        current_positions_risk: float = 0.0,
    ) -> dict[str, Any] | None:
        if cash <= 0 or float(position.get("quantity", 0.0) or 0.0) >= self.min_quantity:
            return None
        fill_price = price * (1 + self.slippage_rate)
        atr = self._calc_atr(candles or [], index)
        sl_mult = max(float(config.parameters.get("stop_loss_atr_multiplier", 2.0) or 2.0), 0.1)
        tp_mult = max(float(config.parameters.get("take_profit_atr_multiplier", 3.0) or 3.0), 0.1)
        stop_loss_price = max(fill_price - (atr * sl_mult if atr > 0 else fill_price * 0.02), 0.0)
        take_profit_price = fill_price + (atr * tp_mult if atr > 0 else fill_price * 0.04)

        if self.position_sizing == "strategy_position_ratio":
            cfg = RiskBudgetConfig(
                risk_per_trade_pct=max(float(config.parameters.get("risk_per_trade_pct", 0.02) or 0.02), 0.0),
                max_total_risk_pct=max(float(config.parameters.get("max_total_risk_pct", 0.06) or 0.06), 0.0),
                max_position_pct=max(float(config.parameters.get("max_position_pct", 1.0) or 1.0), 0.0),
                min_position_value=max(float(config.parameters.get("min_position_value", 10.0) or 10.0), 0.0),
            )
            self.risk_sizer = RiskBudgetSizer(cfg)
            size = self.risk_sizer.calculate(
                account_equity=account_equity if account_equity is not None else cash,
                entry_price=fill_price,
                stop_loss_price=stop_loss_price,
                current_positions_risk=current_positions_risk,
            )
            notional = min(size.notional_value, cash / (1 + self.fee_rate))
        else:
            ratio = max(0.0, min(float(config.parameters.get("position_ratio", 0.2) or 0.2), 1.0))
            notional = cash * ratio
        if notional <= 0:
            return None
        fee = notional * self.fee_rate
        spend_after_fee = max(notional - fee, 0.0)
        quantity = spend_after_fee / fill_price if fill_price > 0 else 0.0
        if quantity < self.min_quantity:
            return None

        position["quantity"] = quantity
        position["avg_price"] = fill_price
        position["stop_loss_price"] = stop_loss_price
        position["take_profit_price"] = take_profit_price
        cash_after = cash - notional
        return {
            "timestamp": timestamp,
            "index": index,
            "strategy_id": config.strategy_id,
            "symbol": symbol,
            "action": "BUY",
            "price": price,
            "fill_price": fill_price,
            "quantity": quantity,
            "notional": notional,
            "fee": fee,
            "slippage": abs(fill_price - price) * quantity,
            "realized_pnl": 0.0,
            "cash_after": cash_after,
            "reason": reason,
            "entry_reason": reason,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "slippage_cost": abs(fill_price - price) * quantity,
        }

    def _strategy_window(self, config: StrategyConfig, candles: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
        params = config.parameters
        if config.type == "bollinger":
            lookback = int(params.get("period", 20) or 20)
        elif config.type == "dual_ma":
            lookback = int(params.get("slow_period", 26) or 26) + 1
        elif config.type == "momentum":
            lookback = int(params.get("lookback_period", 20) or 20) + 1
        elif config.type == "rsi":
            lookback = int(params.get("period", params.get("rsi_period", 14)) or 14) + 1
        elif config.type == "macd":
            lookback = int(params.get("slow_period", 26) or 26) + int(params.get("signal_period", 9) or 9) + 5
        else:
            lookback = index + 1
        safe_lookback = max(1, min(int(lookback or 1), index + 1))
        start = max(0, index + 1 - safe_lookback)
        return candles[start : index + 1]

    def _sell(
        self,
        config: StrategyConfig,
        symbol: str,
        price: float,
        cash: float,
        position: dict[str, float],
        index: int,
        timestamp: str,
        reason: str,
    ) -> dict[str, Any] | None:
        quantity = float(position.get("quantity", 0.0) or 0.0)
        if quantity < self.min_quantity:
            return None
        fill_price = price * (1 - self.slippage_rate)
        gross = quantity * fill_price
        fee = gross * self.fee_rate
        realized_pnl = gross - fee - quantity * float(position.get("avg_price", 0.0) or 0.0)
        cash_after = cash + gross - fee
        position["quantity"] = 0.0
        position["avg_price"] = 0.0
        position["stop_loss_price"] = 0.0
        position["take_profit_price"] = 0.0
        return {
            "timestamp": timestamp,
            "index": index,
            "strategy_id": config.strategy_id,
            "symbol": symbol,
            "action": "SELL",
            "price": price,
            "fill_price": fill_price,
            "quantity": quantity,
            "notional": gross,
            "fee": fee,
            "slippage": abs(price - fill_price) * quantity,
            "realized_pnl": realized_pnl,
            "cash_after": cash_after,
            "reason": reason,
            "exit_reason": self._exit_reason(reason),
            "slippage_cost": abs(price - fill_price) * quantity,
        }

    def _maybe_exit_intrabar(
        self,
        config: StrategyConfig,
        symbol: str,
        candle: dict[str, Any],
        cash: float,
        position: dict[str, float],
        index: int,
        timestamp: str,
    ) -> dict[str, Any] | None:
        quantity = float(position.get("quantity", 0.0) or 0.0)
        if quantity < self.min_quantity:
            return None
        stop_loss = float(position.get("stop_loss_price", 0.0) or 0.0)
        take_profit = float(position.get("take_profit_price", 0.0) or 0.0)
        if stop_loss <= 0 or take_profit <= 0:
            return None
        result = self._detect_intrabar_stop(
            candle,
            entry_price=float(position.get("avg_price", 0.0) or 0.0),
            sl_price=stop_loss,
            tp_price=take_profit,
            direction="long",
        )
        if not result:
            return None
        trade = self._sell(config, symbol, float(result["fill_price"]), cash, position, index, timestamp, str(result["reason"]))
        if trade:
            trade["intrabar"] = True
            trade["trigger"] = result["trigger"]
            trade["exit_reason"] = result["trigger"]
        return trade

    def _diagnostics(self, trades: list[dict[str, Any]], no_entry_counts: dict[str, int]) -> dict[str, Any]:
        exit_counts: dict[str, int] = {}
        for trade in trades:
            if str(trade.get("action", "")).upper() != "SELL":
                continue
            reason = str(trade.get("trigger") or trade.get("exit_reason") or "opposite_signal")
            exit_counts[reason] = exit_counts.get(reason, 0) + 1
        realized = [self._float(trade.get("realized_pnl")) for trade in trades if str(trade.get("action", "")).upper() == "SELL"]
        return create_backtest_diagnostics(
            no_entry_counts=no_entry_counts,
            exit_counts=exit_counts,
            win_pnls=[value for value in realized if value > 0],
            loss_pnls=[value for value in realized if value < 0],
            total_fees=sum(self._float(trade.get("fee")) for trade in trades),
            total_execution_cost=sum(self._float(trade.get("slippage_cost", trade.get("slippage"))) for trade in trades),
        ).to_dict()

    @staticmethod
    def _detect_intrabar_stop(
        candle: dict[str, Any],
        entry_price: float,
        sl_price: float,
        tp_price: float,
        direction: str = "long",
    ) -> dict[str, Any] | None:
        open_price = float(candle.get("open", candle.get("close", 0)) or 0)
        high_price = float(candle.get("high", 0) or 0)
        low_price = float(candle.get("low", 0) or 0)
        if direction == "short":
            sl_hit = high_price >= sl_price
            tp_hit = low_price <= tp_price
        else:
            sl_hit = low_price <= sl_price
            tp_hit = high_price >= tp_price
        if not sl_hit and not tp_hit:
            return None
        if sl_hit and not tp_hit:
            return {"trigger": "sl", "fill_price": sl_price, "reason": "intrabar stop loss triggered"}
        if tp_hit and not sl_hit:
            return {"trigger": "tp", "fill_price": tp_price, "reason": "intrabar take profit triggered"}
        dist_to_sl = abs(open_price - sl_price)
        dist_to_tp = abs(open_price - tp_price)
        if dist_to_tp < dist_to_sl:
            return {"trigger": "tp", "fill_price": tp_price, "reason": "intrabar take profit triggered first"}
        return {"trigger": "sl", "fill_price": sl_price, "reason": "intrabar stop loss triggered first"}

    @staticmethod
    def _calc_atr(candles: list[dict[str, Any]], index: int, period: int = 14) -> float:
        if not candles or index <= 0:
            return 0.0
        start = max(1, index - period + 1)
        true_ranges: list[float] = []
        for i in range(start, index + 1):
            high = float(candles[i].get("high", 0) or 0)
            low = float(candles[i].get("low", 0) or 0)
            previous_close = float(candles[i - 1].get("close", candles[i - 1].get("price", 0)) or 0)
            if high <= 0 or low <= 0:
                continue
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        return fmean(true_ranges) if true_ranges else 0.0

    def _metrics(
        self,
        equity_curve: list[dict[str, Any]],
        drawdown_curve: list[dict[str, Any]],
        trades: list[dict[str, Any]],
    ) -> dict[str, float]:
        equity_values = [self._float(item.get("equity")) for item in equity_curve]
        final_equity = equity_values[-1] if equity_values else self.initial_cash
        total_return = (final_equity - self.initial_cash) / self.initial_cash if self.initial_cash else 0.0
        returns = self._returns(equity_values)
        max_drawdown = max((self._float(item.get("drawdown")) for item in drawdown_curve), default=0.0)
        realized = [self._float(item.get("realized_pnl")) for item in trades if item.get("action") == "SELL"]
        wins = [item for item in realized if item > 0]
        losses = [item for item in realized if item < 0]
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (999.0 if gross_profit > 0 else 0.0)
        annualized_return = self._annualized_return(final_equity, len(equity_values))
        return {
            "final_equity": final_equity,
            "total_return_percent": total_return * 100,
            "max_drawdown_percent": max_drawdown * 100,
            "sharpe_ratio": self._sharpe(returns),
            "calmar_ratio": annualized_return / max_drawdown if max_drawdown > 0 else 0.0,
            "win_rate": (len(wins) / len(realized) * 100) if realized else 0.0,
            "profit_factor": profit_factor,
            "avg_win": fmean(wins) if wins else 0.0,
            "avg_loss": fmean(losses) if losses else 0.0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        }

    def _annualized_return(self, final_equity: float, bar_count: int) -> float:
        if final_equity <= 0 or self.initial_cash <= 0 or bar_count <= 1:
            return 0.0
        periods_per_year = PERIODS_PER_YEAR.get(self.period, PERIODS_PER_YEAR["1h"])
        exponent = periods_per_year / max(bar_count - 1, 1)
        try:
            return (final_equity / self.initial_cash) ** exponent - 1
        except OverflowError:
            return 0.0

    def _drawdown_curve(self, equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
        curve: list[dict[str, Any]] = []
        peak = 0.0
        for item in equity_curve:
            equity = self._float(item.get("equity"))
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak > 0 else 0.0
            curve.append(
                {
                    "index": item.get("index", len(curve)),
                    "timestamp": item.get("timestamp", ""),
                    "equity": equity,
                    "peak": peak,
                    "drawdown": drawdown,
                    "drawdown_percent": drawdown * 100,
                }
            )
        return curve

    def _market_value(self, positions: dict[str, dict[str, float]], prices: dict[str, float]) -> float:
        return sum(float(position.get("quantity", 0.0) or 0.0) * prices.get(symbol, 0.0) for symbol, position in positions.items())

    def _returns(self, equity_values: list[float]) -> list[float]:
        return [(current - previous) / previous for previous, current in zip(equity_values, equity_values[1:]) if previous > 0]

    def _sharpe(self, returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        volatility = pstdev(returns)
        if volatility <= 0:
            return 0.0
        periods_per_year = PERIODS_PER_YEAR.get(self.period, PERIODS_PER_YEAR["1h"])
        return fmean(returns) / volatility * sqrt(periods_per_year)

    def _empty_result(self, config: StrategyConfig, message: str) -> dict[str, Any]:
        return {
            "strategy_id": config.strategy_id,
            "strategy_name": BUILTIN_STRATEGIES[config.type]["name"],
            "strategy_type": config.type,
            "symbols": config.symbols,
            "quote_currency": self.quote_currency,
            "period": self.period,
            "initial_cash": self.initial_cash,
            "final_equity": self.initial_cash,
            "total_return_percent": 0.0,
            "max_drawdown_percent": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "signal_count": 0,
            "trade_count": 0,
            "trades": [],
            "equity_curve": [],
            "drawdown_curve": [],
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "min_quantity": self.min_quantity,
            "position_sizing": self.position_sizing,
            "diagnostics": create_backtest_diagnostics().to_dict(),
            "message": message,
        }

    def _exit_reason(self, reason: str) -> str:
        text = str(reason or "").lower()
        if "stop loss" in text or "止损" in text:
            return "sl"
        if "take profit" in text or "止盈" in text:
            return "tp"
        if "end" in text:
            return "end"
        return "opposite_signal"

    def _timestamp(self, item: dict[str, Any], index: int) -> str:
        return str(item.get("start_time") or item.get("timestamp") or item.get("time") or index)

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
