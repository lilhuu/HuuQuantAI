"""Multi-timeframe signal conflict resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.backtest_validation import HigherTimeframeTrend
from core.crypto_strategy_engine import StrategySignal


@dataclass
class ConflictCandidate:
    """Candidate signal participating in conflict resolution."""

    symbol: str
    timeframe: str
    strategy_id: str
    strategy_type: str
    action: str
    confidence: float
    regime_score: float
    signal: StrategySignal
    reason: str = ""

    @property
    def score(self) -> float:
        return self.confidence * 100 + abs(self.regime_score) * 10


@dataclass
class ConflictResult:
    """Conflict resolution result."""

    winners: list[ConflictCandidate] = field(default_factory=list)
    blocked: list[ConflictCandidate] = field(default_factory=list)
    block_reasons: dict[str, str] = field(default_factory=dict)
    max_positions: int = 2


class ConflictResolver:
    """Resolve competing strategy signals across symbols and timeframes."""

    MEAN_REVERSION_TYPES = {"bollinger", "rsi"}

    def __init__(self, max_positions: int = 2):
        self.max_positions = max(1, int(max_positions or 1))

    def resolve(
        self,
        signals: list[StrategySignal],
        higher_tf_trends: dict[str, HigherTimeframeTrend] | None = None,
    ) -> ConflictResult:
        candidates = [
            ConflictCandidate(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                strategy_id=signal.strategy_id,
                strategy_type=signal.strategy_type,
                action=signal.action,
                confidence=signal.confidence,
                regime_score=signal.regime_score,
                signal=signal,
            )
            for signal in signals
            if signal.action in {"BUY", "SELL"}
        ]
        if not candidates:
            return ConflictResult(max_positions=self.max_positions)

        by_symbol: dict[str, list[ConflictCandidate]] = {}
        for candidate in candidates:
            by_symbol.setdefault(candidate.symbol, []).append(candidate)

        trends = higher_tf_trends or {}
        symbol_winners: list[ConflictCandidate] = []
        blocked: list[ConflictCandidate] = []
        block_reasons: dict[str, str] = {}

        for symbol, group in by_symbol.items():
            actions = {item.action for item in group}
            if "BUY" in actions and "SELL" in actions:
                reason = (
                    f"timeframe_conflict: BUY+SELL on {symbol} "
                    f"({', '.join(f'{item.timeframe}:{item.action}' for item in group)})"
                )
                for item in group:
                    item.reason = reason
                blocked.extend(group)
                block_reasons[symbol] = reason
                continue

            survivors: list[ConflictCandidate] = []
            trend = trends.get(symbol)
            for item in group:
                reason = self._higher_tf_block_reason(item, trend)
                if reason:
                    item.reason = reason
                    blocked.append(item)
                    block_reasons.setdefault(symbol, reason)
                    continue
                survivors.append(item)

            if not survivors:
                block_reasons.setdefault(symbol, "higher_tf_trend_block")
                continue

            survivors.sort(key=lambda item: item.score, reverse=True)
            symbol_winners.append(survivors[0])
            for item in survivors[1:]:
                item.reason = "ranked_out"
                blocked.append(item)

        symbol_winners.sort(key=lambda item: item.score, reverse=True)
        winners = symbol_winners[: self.max_positions]
        for item in symbol_winners[self.max_positions :]:
            item.reason = "max_positions_limit"
            blocked.append(item)

        return ConflictResult(
            winners=winners,
            blocked=blocked,
            block_reasons=block_reasons,
            max_positions=self.max_positions,
        )

    def _higher_tf_block_reason(
        self,
        candidate: ConflictCandidate,
        trend: HigherTimeframeTrend | None,
    ) -> str:
        if candidate.strategy_type not in self.MEAN_REVERSION_TYPES or trend is None or trend.is_neutral:
            return ""
        if candidate.action == "BUY" and trend.is_down:
            return "higher_tf_trend_block: down trend blocks mean-reversion BUY"
        if candidate.action == "SELL" and trend.is_up:
            return "higher_tf_trend_block: up trend blocks mean-reversion SELL"
        return ""
