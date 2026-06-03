"""Seven-factor crypto market regime detector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MarketRegime(str, Enum):
    """Supported market regime labels."""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeFeatures:
    """Raw normalized factor values used by the regime detector."""

    trend_strength: float = 0.0
    momentum: float = 0.0
    volume_anomaly: float = 0.0
    orderbook_imbalance: float = 0.0
    funding_overheat: float = 0.0
    volatility_spike: float = 0.0
    oi_change: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class RegimeResult:
    """Complete regime classification result."""

    regime: MarketRegime = MarketRegime.UNKNOWN
    score: float = 0.0
    features: RegimeFeatures = field(default_factory=RegimeFeatures)
    confidence: float = 0.0
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "score": self.score,
            "features": self.features.to_dict(),
            "confidence": self.confidence,
            "description": self.description,
        }


@dataclass
class RegimeDetectorConfig:
    trend_threshold: float = 0.35
    trend_multiplier: float = 15.0
    symbol_trend_multipliers: dict[str, float] = field(default_factory=dict)


class RegimeDetector:
    """Detect crypto market state using trend, flow, funding, and risk factors."""

    WEIGHTS = {
        "trend_strength": 0.30,
        "momentum": 0.15,
        "oi_change": 0.15,
        "orderbook_imbalance": 0.15,
        "funding_overheat": -0.10,
        "volatility_spike": -0.10,
    }

    TREND_MULTIPLIER = 15.0
    MOMENTUM_MULTIPLIER = 20.0
    OI_MULTIPLIER = 10.0
    VOLATILITY_OFFSET = 0.04
    VOLATILITY_DIVISOR = 0.04
    FUNDING_DIVISOR = 0.001
    VOLUME_ANOMALY_THRESHOLD = 2.0

    def __init__(
        self,
        trend_threshold: float = 0.35,
        *,
        trend_multiplier: float | None = None,
        symbol_trend_multipliers: dict[str, float] | None = None,
        config: dict[str, Any] | RegimeDetectorConfig | None = None,
    ) -> None:
        if isinstance(config, RegimeDetectorConfig):
            cfg = config
        else:
            payload = dict(config or {})
            cfg = RegimeDetectorConfig(
                trend_threshold=float(payload.get("trend_threshold", trend_threshold) or trend_threshold),
                trend_multiplier=float(payload.get("trend_multiplier", trend_multiplier or self.TREND_MULTIPLIER) or self.TREND_MULTIPLIER),
                symbol_trend_multipliers=dict(payload.get("symbol_trend_multipliers") or symbol_trend_multipliers or {}),
            )
        self.trend_threshold = max(0.05, min(0.95, float(cfg.trend_threshold or 0.35)))
        self.trend_multiplier = max(0.1, float(cfg.trend_multiplier or self.TREND_MULTIPLIER))
        self.symbol_trend_multipliers = {str(key).upper(): max(0.1, float(value)) for key, value in cfg.symbol_trend_multipliers.items()}

    def detect(
        self,
        closes: list[float],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        volumes: list[float] | None = None,
        funding_rate: float | None = None,
        orderbook_bid_depth: float | None = None,
        orderbook_ask_depth: float | None = None,
        open_interest_current: float | None = None,
        open_interest_previous: float | None = None,
        symbol: str | None = None,
    ) -> RegimeResult:
        """Compute a market regime from available factors."""

        clean_closes = [self._float(value) for value in closes or [] if self._float(value) > 0]
        if len(clean_closes) < 5:
            features = RegimeFeatures()
            return RegimeResult(
                regime=MarketRegime.UNKNOWN,
                score=0.0,
                features=features,
                confidence=0.0,
                description="regime=UNKNOWN | insufficient market data",
            )

        features = self._compute_features(
            clean_closes,
            [self._float(value) for value in highs or []],
            [self._float(value) for value in lows or []],
            [self._float(value) for value in volumes or []],
            funding_rate,
            orderbook_bid_depth,
            orderbook_ask_depth,
            open_interest_current,
            open_interest_previous,
            symbol,
        )
        score = self._compute_score(features)
        regime = self._classify(score, features.volatility_spike)
        confidence = self._compute_confidence(features)
        description = self._describe(regime, score, features)
        return RegimeResult(
            regime=regime,
            score=round(score, 4),
            features=features,
            confidence=round(confidence, 4),
            description=description,
        )

    def _compute_features(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
        funding_rate: float | None,
        bid_depth: float | None,
        ask_depth: float | None,
        oi_current: float | None,
        oi_previous: float | None,
        symbol: str | None,
    ) -> RegimeFeatures:
        return RegimeFeatures(
            trend_strength=self._calc_trend_strength(closes, symbol=symbol),
            momentum=self._calc_momentum(closes),
            volume_anomaly=self._calc_volume_anomaly(volumes),
            orderbook_imbalance=self._calc_orderbook_imbalance(bid_depth, ask_depth),
            funding_overheat=self._calc_funding_overheat(funding_rate),
            volatility_spike=self._calc_volatility_spike(closes, highs, lows),
            oi_change=self._calc_oi_change(oi_current, oi_previous),
        )

    def _calc_trend_strength(self, closes: list[float], *, symbol: str | None = None) -> float:
        if len(closes) < 40:
            return 0.0
        previous = sum(closes[-40:-20]) / 20
        recent = sum(closes[-20:]) / 20
        if previous == 0:
            return 0.0
        slope = (recent - previous) / previous
        return self._clamp(slope * self._trend_multiplier_for(symbol), -1.0, 1.0)

    def _trend_multiplier_for(self, symbol: str | None) -> float:
        if symbol:
            normalized = str(symbol).upper()
            if normalized in self.symbol_trend_multipliers:
                return self.symbol_trend_multipliers[normalized]
            base = normalized.split("/", 1)[0]
            if base in self.symbol_trend_multipliers:
                return self.symbol_trend_multipliers[base]
        return self.trend_multiplier

    def _calc_momentum(self, closes: list[float]) -> float:
        if len(closes) < 5 or closes[-5] == 0:
            return 0.0
        change = (closes[-1] - closes[-5]) / closes[-5]
        return self._clamp(change * self.MOMENTUM_MULTIPLIER, -1.0, 1.0)

    def _calc_oi_change(self, oi_current: float | None, oi_previous: float | None) -> float:
        if oi_current is None or oi_previous in (None, 0):
            return 0.0
        change = (float(oi_current) - float(oi_previous)) / float(oi_previous)
        return self._clamp(change * self.OI_MULTIPLIER, -1.0, 1.0)

    def _calc_orderbook_imbalance(self, bid_depth: float | None, ask_depth: float | None) -> float:
        if bid_depth is None or ask_depth is None:
            return 0.0
        total = float(bid_depth) + float(ask_depth)
        if total == 0:
            return 0.0
        return self._clamp((float(bid_depth) - float(ask_depth)) / total, -1.0, 1.0)

    def _calc_funding_overheat(self, funding_rate: float | None) -> float:
        if funding_rate is None:
            return 0.0
        return self._clamp(abs(float(funding_rate)) / self.FUNDING_DIVISOR, 0.0, 1.0)

    def _calc_volatility_spike(self, closes: list[float], highs: list[float], lows: list[float]) -> float:
        if len(closes) < 2:
            return 0.0

        parkinson_vol = 0.0
        if len(highs) >= 24 and len(lows) >= 24:
            ranges = []
            for high, low in zip(highs[-24:], lows[-24:]):
                if low > 0:
                    ranges.append((high - low) / low)
            if ranges:
                parkinson_vol = sum(ranges) / len(ranges)

        returns = []
        span = min(24, len(closes))
        for index in range(-span, -1):
            if closes[index] != 0:
                returns.append((closes[index + 1] - closes[index]) / closes[index])

        close_vol = 0.0
        if returns:
            mean_return = sum(returns) / len(returns)
            variance = sum((item - mean_return) ** 2 for item in returns) / len(returns)
            close_vol = variance**0.5

        volatility = max(parkinson_vol, close_vol)
        return self._clamp((volatility - self.VOLATILITY_OFFSET) / self.VOLATILITY_DIVISOR, 0.0, 1.0)

    def _calc_volume_anomaly(self, volumes: list[float]) -> float:
        if len(volumes) < 21:
            return 0.0
        average = sum(volumes[-21:-1]) / 20
        if average == 0:
            return 0.0
        ratio = volumes[-1] / average
        return self._clamp((ratio - 1.0) / self.VOLUME_ANOMALY_THRESHOLD, 0.0, 1.0)

    def _compute_score(self, features: RegimeFeatures) -> float:
        raw = (
            features.trend_strength * self.WEIGHTS["trend_strength"]
            + features.momentum * self.WEIGHTS["momentum"]
            + features.oi_change * self.WEIGHTS["oi_change"]
            + features.orderbook_imbalance * self.WEIGHTS["orderbook_imbalance"]
            + features.funding_overheat * self.WEIGHTS["funding_overheat"]
            + features.volatility_spike * self.WEIGHTS["volatility_spike"]
        )
        return self._clamp(raw, -1.0, 1.0)

    def _classify(self, score: float, volatility_spike: float) -> MarketRegime:
        if volatility_spike > 0.85:
            return MarketRegime.RISK_OFF
        if score > self.trend_threshold:
            return MarketRegime.TREND_UP
        if score < -self.trend_threshold:
            return MarketRegime.TREND_DOWN
        return MarketRegime.RANGE

    def _compute_confidence(self, features: RegimeFeatures) -> float:
        confidence = 0.5
        for value in (
            features.trend_strength,
            features.momentum,
            features.oi_change,
            features.orderbook_imbalance,
            features.funding_overheat,
            features.volatility_spike,
        ):
            if value != 0.0:
                confidence += 0.08
        return min(1.0, confidence)

    def _describe(self, regime: MarketRegime, score: float, features: RegimeFeatures) -> str:
        parts = [f"regime={regime.value}", f"score={score:.3f}"]
        if features.volatility_spike > 0.5:
            parts.append("高波动")
        if features.funding_overheat > 0.5:
            parts.append("资金费率过热")
        if features.volume_anomaly > 0.5:
            parts.append("成交量异常")
        return " | ".join(parts)

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, float(value)))
