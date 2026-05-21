"""Higher-timeframe trend helpers for strategy validation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Any


@dataclass
class HigherTimeframeTrend:
    """Trend direction inferred from higher timeframe price changes."""

    direction: str = "neutral"
    four_hour_change_pct: float = 0.0
    daily_change_pct: float = 0.0

    @property
    def is_up(self) -> bool:
        return self.direction == "up"

    @property
    def is_down(self) -> bool:
        return self.direction == "down"

    @property
    def is_neutral(self) -> bool:
        return self.direction == "neutral"


@dataclass
class BacktestDiagnostics:
    """Diagnostics explaining missing entries, exits, and execution cost."""

    no_entry_reasons: list[dict[str, Any]]
    stop_loss_count: int = 0
    take_profit_count: int = 0
    opposite_signal_count: int = 0
    end_exit_count: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_fees: float = 0.0
    total_execution_cost: float = 0.0
    fee_slippage_to_gross_profit_pct: float = 0.0
    train_trades: int | None = None
    validation_trades: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "no_entry_reasons": self.no_entry_reasons,
            "stop_loss_count": self.stop_loss_count,
            "take_profit_count": self.take_profit_count,
            "opposite_signal_count": self.opposite_signal_count,
            "end_exit_count": self.end_exit_count,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "total_fees": self.total_fees,
            "total_execution_cost": self.total_execution_cost,
            "fee_slippage_to_gross_profit_pct": self.fee_slippage_to_gross_profit_pct,
            "train_trades": self.train_trades,
            "validation_trades": self.validation_trades,
        }


def categorize_no_entry_reason(strategy_type: str, reasoning: str) -> str:
    """Classify why a strategy did not produce an entry on a bar."""
    text = f"{strategy_type} {reasoning}".lower()
    if "risk_off" in text or "risk kill" in text:
        return "risk_off_blocked"
    if "macro" in text or "宏观" in text:
        return "macro_gate_blocked"
    if "regime" in text and "range" in text and any(token in text for token in ("trend", "breakout", "momentum")):
        return "trend_regime_not_ready"
    if any(token in text for token in ("未共振", "breakout", "momentum", "macd", "trend breakout")):
        return "trend_filters_not_aligned"
    if "趋势环境" in text or ("mean reversion" in text and "regime" in text):
        return "mean_reversion_wrong_regime"
    if "高周期" in text or "higher timeframe" in text:
        return "higher_timeframe_trend_blocked"
    if "波动率" in text or "volatility" in text:
        return "volatility_expansion_blocked"
    if any(token in text for token in ("布林", "rsi", "mean reversion")):
        return "mean_reversion_not_extreme"
    return "other_hold"


def create_backtest_diagnostics(
    *,
    no_entry_counts: dict[str, int] | None = None,
    exit_counts: dict[str, int] | None = None,
    win_pnls: list[float] | None = None,
    loss_pnls: list[float] | None = None,
    total_fees: float = 0.0,
    total_execution_cost: float = 0.0,
    train_trades: int | None = None,
    validation_trades: int | None = None,
) -> BacktestDiagnostics:
    """Build a compact diagnostics payload for API responses."""
    no_entries = [
        {"reason": reason, "count": int(count)}
        for reason, count in sorted((no_entry_counts or {}).items(), key=lambda item: item[1], reverse=True)
        if count
    ]
    exits = exit_counts or {}
    wins = [float(item) for item in (win_pnls or []) if float(item) > 0]
    losses = [float(item) for item in (loss_pnls or []) if float(item) < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    costs = float(total_fees or 0.0) + float(total_execution_cost or 0.0)
    return BacktestDiagnostics(
        no_entry_reasons=no_entries,
        stop_loss_count=int(exits.get("sl", 0) + exits.get("stop_loss", 0)),
        take_profit_count=int(exits.get("tp", 0) + exits.get("take_profit", 0)),
        opposite_signal_count=int(exits.get("opposite_signal", 0) + exits.get("signal", 0)),
        end_exit_count=int(exits.get("end", 0)),
        avg_win=fmean(wins) if wins else 0.0,
        avg_loss=fmean(losses) if losses else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        total_fees=float(total_fees or 0.0),
        total_execution_cost=float(total_execution_cost or 0.0),
        fee_slippage_to_gross_profit_pct=(costs / gross_profit * 100) if gross_profit > 0 else 0.0,
        train_trades=train_trades,
        validation_trades=validation_trades,
    )


def build_higher_timeframe_trend(
    ohlcv: list[dict[str, Any]],
    timeframe: str = "1h",
) -> HigherTimeframeTrend:
    """Build a coarse higher-timeframe trend judgment from OHLCV rows.

    The helper is intentionally simple and deterministic. It is used by the
    conflict resolver to block mean-reversion signals that fight a strong
    higher-timeframe trend.
    """
    closes = [_safe_float(row.get("close", row.get("price"))) for row in ohlcv or []]
    closes = [value for value in closes if value > 0]
    if len(closes) < 2:
        return HigherTimeframeTrend()

    bars_per_4h, bars_per_day = _bars_for_timeframe(timeframe)
    four_hour_lookback = max(1, bars_per_4h * 12)
    daily_lookback = max(1, bars_per_day * 10)

    four_hour_change = _window_change_pct(closes, four_hour_lookback)
    daily_change = _window_change_pct(closes, daily_lookback)

    if four_hour_change >= 1.5 and daily_change >= 2.0:
        direction = "up"
    elif four_hour_change <= -1.5 and daily_change <= -2.0:
        direction = "down"
    else:
        direction = "neutral"

    return HigherTimeframeTrend(
        direction=direction,
        four_hour_change_pct=round(four_hour_change, 4),
        daily_change_pct=round(daily_change, 4),
    )


def _bars_for_timeframe(timeframe: str) -> tuple[int, int]:
    value = str(timeframe or "1h").lower()
    if value == "1m":
        return 240, 1440
    if value == "5m":
        return 48, 288
    if value == "15m":
        return 16, 96
    if value == "4h":
        return 1, 6
    if value == "1d":
        return 1, 1
    return 4, 24


def _window_change_pct(closes: list[float], lookback: int) -> float:
    if lookback <= 0 or len(closes) <= lookback:
        return 0.0
    base = closes[-lookback - 1]
    if base <= 0:
        return 0.0
    return (closes[-1] - base) / base * 100


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
