"""Higher-timeframe trend helpers for strategy validation."""

from __future__ import annotations

from dataclasses import dataclass
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
