"""Macro risk scoring and three-level gate decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from core.macro_data_provider import MacroSnapshot


class MacroGateState(str, Enum):
    """Macro gate states for new risk exposure."""

    BLOCK_NEW_RISK = "BLOCK_NEW_RISK"
    ALLOW_REDUCED = "ALLOW_REDUCED"
    ALLOW_FULL = "ALLOW_FULL"


@dataclass
class MacroGateDecision:
    """Macro gate decision with position and signal adjustments."""

    state: MacroGateState = MacroGateState.ALLOW_FULL
    score: float = 0.0
    reason: str = ""

    position_size_multiplier: float = 1.0
    max_concurrent_positions: int = 2
    confidence_penalty: float = 0.0
    entry_threshold_adjustment: float = 0.0

    dxy_change_pct: float = 0.0
    m2_change_pct: float = 0.0
    btc_dom_change_pct: float = 0.0
    yield_spread: float = 0.0
    gold_change_pct: float = 0.0
    spx_change_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


class MacroRiskEvaluator:
    """Evaluate macro liquidity and risk signals for crypto trading."""

    BLOCK_THRESHOLD = -0.30
    REDUCE_THRESHOLD = -0.10
    RISK_ON_THRESHOLD = 0.20

    WEIGHT_M2 = 0.50
    WEIGHT_DXY = 0.30
    WEIGHT_BTC_DOM = 0.20

    PENALTY_YIELD_INVERSION = 0.10
    PENALTY_GOLD_SURGE = 0.10

    def evaluate(self, snapshot: MacroSnapshot) -> MacroGateDecision:
        score = self._compute_macro_score(snapshot)
        state = self._classify_gate(score, snapshot)
        reason = self._build_reason(state, score, snapshot)

        if state == MacroGateState.BLOCK_NEW_RISK:
            return self._decision(
                snapshot,
                state=state,
                score=score,
                reason=reason,
                position_size_multiplier=0.0,
                max_concurrent_positions=0,
                confidence_penalty=100.0,
                entry_threshold_adjustment=100.0,
            )
        if state == MacroGateState.ALLOW_REDUCED:
            return self._decision(
                snapshot,
                state=state,
                score=score,
                reason=reason,
                position_size_multiplier=0.5,
                max_concurrent_positions=1,
                confidence_penalty=8.0,
                entry_threshold_adjustment=8.0,
            )
        return self._decision(
            snapshot,
            state=state,
            score=score,
            reason=reason,
            position_size_multiplier=1.0,
            max_concurrent_positions=2,
            confidence_penalty=0.0,
            entry_threshold_adjustment=0.0,
        )

    def _compute_macro_score(self, snapshot: MacroSnapshot) -> float:
        score = 0.0
        weight_total = 0.0

        if snapshot.m2_available:
            m2_score = self._clamp(snapshot.m2_change_3m_pct / 35.0, -1.0, 1.0)
            score += m2_score * self.WEIGHT_M2
            weight_total += self.WEIGHT_M2

        if snapshot.dxy_available:
            dxy_score = -self._clamp(snapshot.dxy_change_30d_pct / 5.0, -1.0, 1.0)
            score += dxy_score * self.WEIGHT_DXY
            weight_total += self.WEIGHT_DXY

        if snapshot.btc_dom_available:
            btc_dom_score = -self._clamp(snapshot.btc_dom_change_30d_pct / 10.0, -1.0, 1.0)
            score += btc_dom_score * self.WEIGHT_BTC_DOM
            weight_total += self.WEIGHT_BTC_DOM

        if weight_total <= 0:
            return 0.0
        score = score / weight_total

        if snapshot.yields_available and snapshot.yield_spread_10y2y < 0:
            inversion_penalty = abs(min(0.0, snapshot.yield_spread_10y2y) / 2.0)
            score -= inversion_penalty * self.PENALTY_YIELD_INVERSION

        if snapshot.gold_available and snapshot.gold_change_30d_pct > 3.0:
            gold_penalty = min(1.0, (snapshot.gold_change_30d_pct - 3.0) / 7.0)
            score -= gold_penalty * self.PENALTY_GOLD_SURGE

        return self._clamp(score, -1.0, 1.0)

    def _classify_gate(self, score: float, snapshot: MacroSnapshot) -> MacroGateState:
        if snapshot.dxy_available and snapshot.m2_available:
            if snapshot.dxy_change_30d_pct > 1.0 and snapshot.m2_change_3m_pct < -1.0:
                return MacroGateState.BLOCK_NEW_RISK

        if score <= self.BLOCK_THRESHOLD:
            return MacroGateState.BLOCK_NEW_RISK
        if score <= self.REDUCE_THRESHOLD:
            return MacroGateState.ALLOW_REDUCED
        return MacroGateState.ALLOW_FULL

    def _build_reason(self, state: MacroGateState, score: float, snapshot: MacroSnapshot) -> str:
        parts = [f"macro_score={score:.3f}"]
        if snapshot.dxy_available:
            parts.append(f"DXY_30d={snapshot.dxy_change_30d_pct:+.2f}%")
        if snapshot.m2_available:
            parts.append(f"M2_3m={snapshot.m2_change_3m_pct:+.2f}%")
        if snapshot.btc_dom_available:
            parts.append(f"BTC.D_30d={snapshot.btc_dom_change_30d_pct:+.2f}%")
        if snapshot.yields_available and snapshot.yield_spread_10y2y < 0:
            parts.append(f"YIELD_INVERTED={snapshot.yield_spread_10y2y:+.2f}%")
        if snapshot.gold_available and snapshot.gold_change_30d_pct > 3.0:
            parts.append(f"GOLD_SURGE={snapshot.gold_change_30d_pct:+.2f}%")

        detail = " | ".join(parts)
        if state == MacroGateState.BLOCK_NEW_RISK:
            return f"BLOCK: 宏观环境不利，禁止开新仓。{detail}"
        if state == MacroGateState.ALLOW_REDUCED:
            return f"REDUCED: 宏观环境偏谨慎，仓位减半。{detail}"
        return f"ALLOW: 宏观环境正常。{detail}"

    def _decision(
        self,
        snapshot: MacroSnapshot,
        state: MacroGateState,
        score: float,
        reason: str,
        position_size_multiplier: float,
        max_concurrent_positions: int,
        confidence_penalty: float,
        entry_threshold_adjustment: float,
    ) -> MacroGateDecision:
        return MacroGateDecision(
            state=state,
            score=round(score, 4),
            reason=reason,
            position_size_multiplier=position_size_multiplier,
            max_concurrent_positions=max_concurrent_positions,
            confidence_penalty=confidence_penalty,
            entry_threshold_adjustment=entry_threshold_adjustment,
            dxy_change_pct=snapshot.dxy_change_30d_pct,
            m2_change_pct=snapshot.m2_change_3m_pct,
            btc_dom_change_pct=snapshot.btc_dom_change_30d_pct,
            yield_spread=snapshot.yield_spread_10y2y,
            gold_change_pct=snapshot.gold_change_30d_pct,
            spx_change_pct=snapshot.spx_change_30d_pct,
        )

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, float(value)))
