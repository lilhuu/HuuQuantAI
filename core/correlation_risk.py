"""Correlation-aware position reduction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CorrelationPair:
    symbol_a: str
    symbol_b: str
    correlation: float
    data_points: int
    is_significant: bool = True


@dataclass
class CorrelationMatrix:
    pairs: dict[tuple[str, str], CorrelationPair] = field(default_factory=dict)

    def get(self, symbol_a: str, symbol_b: str) -> float:
        if symbol_a == symbol_b:
            return 1.0
        pair = self.pairs.get(tuple(sorted([symbol_a, symbol_b])))
        if pair is None or not pair.is_significant:
            return 0.0
        return pair.correlation

    def is_highly_correlated(self, symbol_a: str, symbol_b: str, threshold: float = 0.7) -> bool:
        return abs(self.get(symbol_a, symbol_b)) >= threshold


class CorrelationCalculator:
    def __init__(self, window: int = 30, min_points: int = 20):
        self.window = max(int(window or 30), 2)
        self.min_points = max(int(min_points or 20), 2)

    def compute_matrix(self, market_data: dict[str, list[dict[str, Any]]]) -> CorrelationMatrix:
        returns: dict[str, list[float]] = {}
        for symbol, candles in (market_data or {}).items():
            closes = [self._float(row.get("close", row.get("price"))) for row in candles]
            closes = [item for item in closes if item > 0][-self.window - 1 :]
            series = [(b - a) / a for a, b in zip(closes, closes[1:]) if a > 0]
            if len(series) >= 2:
                returns[symbol] = series

        pairs: dict[tuple[str, str], CorrelationPair] = {}
        symbols = list(returns)
        for index, symbol_a in enumerate(symbols):
            for symbol_b in symbols[index + 1 :]:
                corr, n = self._pearson(returns[symbol_a], returns[symbol_b])
                pairs[tuple(sorted([symbol_a, symbol_b]))] = CorrelationPair(
                    symbol_a=symbol_a,
                    symbol_b=symbol_b,
                    correlation=round(corr, 4),
                    data_points=n,
                    is_significant=n >= self.min_points,
                )
        return CorrelationMatrix(pairs=pairs)

    def _pearson(self, left: list[float], right: list[float]) -> tuple[float, int]:
        n = min(len(left), len(right))
        if n < 2:
            return 0.0, n
        x = left[-n:]
        y = right[-n:]
        mx = sum(x) / n
        my = sum(y) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
        sx = sum((a - mx) ** 2 for a in x) ** 0.5
        sy = sum((b - my) ** 2 for b in y) ** 0.5
        if sx <= 0 or sy <= 0:
            return 0.0, n
        return cov / (sx * sy), n

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


@dataclass
class CorrelationAdjustedPosition:
    symbol: str
    original_ratio: float
    adjusted_ratio: float
    multiplier: float
    correlated_with: list[str]
    reason: str = ""


class CorrelationPositionSizer:
    CORRELATION_THRESHOLD = 0.7
    MIN_MULTIPLIER = 0.25

    def adjust(
        self,
        signals: list[dict[str, Any]],
        corr_matrix: CorrelationMatrix,
    ) -> list[CorrelationAdjustedPosition]:
        results: list[CorrelationAdjustedPosition] = []
        for signal in signals or []:
            symbol = str(signal.get("symbol", ""))
            action = str(signal.get("action", "")).upper()
            original = float(signal.get("position_ratio", 1.0) or 0)
            correlated = [
                str(other.get("symbol", ""))
                for other in signals
                if other is not signal
                and str(other.get("action", "")).upper() == action
                and corr_matrix.is_highly_correlated(symbol, str(other.get("symbol", "")), self.CORRELATION_THRESHOLD)
            ]
            if not correlated:
                results.append(CorrelationAdjustedPosition(symbol, original, original, 1.0, [], "no correlated same-direction signal"))
                continue
            multiplier = max(self.MIN_MULTIPLIER, 1.0 / (1 + len(correlated)))
            results.append(
                CorrelationAdjustedPosition(
                    symbol=symbol,
                    original_ratio=original,
                    adjusted_ratio=round(original * multiplier, 8),
                    multiplier=round(multiplier, 8),
                    correlated_with=correlated,
                    reason=f"correlated with {', '.join(correlated)}",
                )
            )
        return results
