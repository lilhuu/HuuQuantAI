"""Crypto-only strategy engine for signals, aggregation, and backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from statistics import fmean, pstdev
from typing import Any, Dict, Iterable, List

from core.crypto_market_data_provider import normalize_crypto_symbol
from core.macro_risk import MacroGateDecision, MacroGateState
from core.regime_detector import MarketRegime


BUILTIN_STRATEGIES: dict[str, dict[str, Any]] = {
    "dual_ma": {
        "type": "dual_ma",
        "name": "Dual MA Crossover",
        "description": "Trend-following signals from fast and slow moving-average crosses.",
        "parameters": {"fast_period": 12, "slow_period": 26, "position_ratio": 0.2, "stop_loss_atr_multiplier": 2.0, "take_profit_atr_multiplier": 3.0, "risk_per_trade_pct": 0.02},
    },
    "rsi": {
        "type": "rsi",
        "name": "RSI Mean Reversion",
        "description": "Buy when RSI is oversold and sell when RSI is overbought.",
        "parameters": {"period": 14, "oversold": 30, "overbought": 70, "position_ratio": 0.2, "stop_loss_atr_multiplier": 1.5, "take_profit_atr_multiplier": 2.5, "risk_per_trade_pct": 0.02},
    },
    "macd": {
        "type": "macd",
        "name": "MACD Trend",
        "description": "Trend signals from DIF/DEA crossovers.",
        "parameters": {"fast_period": 12, "slow_period": 26, "signal_period": 9, "position_ratio": 0.2, "stop_loss_atr_multiplier": 2.0, "take_profit_atr_multiplier": 3.0, "risk_per_trade_pct": 0.02},
    },
    "bollinger": {
        "type": "bollinger",
        "name": "Bollinger Mean Reversion",
        "description": "Buy lower-band extremes and sell upper-band extremes, with optional higher-timeframe trend protection.",
        "parameters": {"period": 20, "stddev_multiplier": 2.0, "position_ratio": 0.2, "stop_loss_atr_multiplier": 1.5, "take_profit_atr_multiplier": 1.0, "risk_per_trade_pct": 0.02, "use_higher_tf_trend_filter": True},
    },
    "momentum": {
        "type": "momentum",
        "name": "Momentum Breakout",
        "description": "Generate signals when lookback returns break configured thresholds.",
        "parameters": {"lookback_period": 20, "buy_threshold": 0.03, "sell_threshold": -0.02, "position_ratio": 0.2, "stop_loss_atr_multiplier": 2.0, "take_profit_atr_multiplier": 4.0, "risk_per_trade_pct": 0.02},
    },
}


@dataclass
class StrategyConfig:
    strategy_id: str
    type: str
    symbols: list[str]
    weight: float = 1.0
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategySignal:
    strategy_id: str
    strategy_name: str
    strategy_type: str
    symbol: str
    action: str
    price: float
    confidence: float
    weight: float
    weighted_score: float
    reason: str
    timestamp: str
    timeframe: str = "1h"
    indicators: dict[str, float] = field(default_factory=dict)
    regime_score: float = 0.0
    blocked: bool = False
    block_reason: str = ""
    macro_gate_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "strategy_type": self.strategy_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "action": self.action,
            "price": self.price,
            "confidence": self.confidence,
            "weight": self.weight,
            "weighted_score": self.weighted_score,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "indicators": self.indicators,
            "regime_score": self.regime_score,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "macro_gate_state": self.macro_gate_state,
        }


class CryptoStrategyEngine:
    """Evaluate built-in crypto strategies without placing orders."""

    REGIME_STRATEGY_COMPAT: dict[str, set[MarketRegime]] = {
        "dual_ma": {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN},
        "momentum": {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN},
        "macd": {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN},
        "bollinger": {MarketRegime.RANGE},
        "rsi": {MarketRegime.RANGE},
    }

    def list_templates(self) -> list[dict[str, Any]]:
        return [
            {
                "type": key,
                "name": value["name"],
                "description": value["description"],
                "default_parameters": dict(value["parameters"]),
            }
            for key, value in BUILTIN_STRATEGIES.items()
        ]

    def normalize_configs(self, raw_configs: Iterable[dict[str, Any]], default_symbols: list[str]) -> list[StrategyConfig]:
        configs: list[StrategyConfig] = []
        for index, raw in enumerate(raw_configs or []):
            strategy_type = str(raw.get("type") or "dual_ma").strip().lower()
            if strategy_type not in BUILTIN_STRATEGIES:
                raise ValueError(f"unsupported strategy type: {strategy_type}")
            template = BUILTIN_STRATEGIES[strategy_type]
            strategy_id = str(raw.get("strategy_id") or f"{strategy_type}_{index + 1}").strip()
            symbols = [normalize_crypto_symbol(item) for item in raw.get("symbols") or default_symbols]
            symbols = [symbol for symbol in symbols if symbol]
            parameters = {**template["parameters"], **(raw.get("parameters") or {})}
            configs.append(
                StrategyConfig(
                    strategy_id=strategy_id,
                    type=strategy_type,
                    symbols=symbols or list(default_symbols),
                    weight=max(0.0, float(raw.get("weight", 1.0) or 1.0)),
                    enabled=bool(raw.get("enabled", True)),
                    parameters=parameters,
                )
            )
        if not configs:
            configs = [
                StrategyConfig(
                    strategy_id="dual_ma_default",
                    type="dual_ma",
                    symbols=list(default_symbols),
                    parameters=dict(BUILTIN_STRATEGIES["dual_ma"]["parameters"]),
                )
            ]
        return configs

    def run(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        configs: list[StrategyConfig],
        conflict_threshold: float = 0.15,
        regimes: dict[str, MarketRegime | str] | None = None,
        regime_scores: dict[str, float] | None = None,
        macro_gate: MacroGateDecision | None = None,
        higher_tf_trends: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signals: list[StrategySignal] = []
        blocked_signals: list[StrategySignal] = []
        strategy_results: list[dict[str, Any]] = []
        for config in configs:
            strategy_signals: list[StrategySignal] = []
            if config.enabled:
                for symbol in config.symbols:
                    candles = market_data.get(symbol, [])
                    effective_config = self._with_higher_tf_trend(config, (higher_tf_trends or {}).get(symbol))
                    signal = self.evaluate_strategy_with_regime(
                        effective_config,
                        symbol,
                        candles,
                        regime=(regimes or {}).get(symbol),
                        regime_score=float((regime_scores or {}).get(symbol, 0.0) or 0.0),
                    )
                    if signal:
                        signal = self.apply_macro_gate(signal, macro_gate)
                        if signal.blocked:
                            blocked_signals.append(signal)
                        strategy_signals.append(signal)
                        signals.append(signal)
            strategy_results.append(
                {
                    "strategy_id": config.strategy_id,
                    "strategy_name": BUILTIN_STRATEGIES[config.type]["name"],
                    "strategy_type": config.type,
                    "enabled": config.enabled,
                    "weight": config.weight,
                    "symbols": config.symbols,
                    "signals": [item.to_dict() for item in strategy_signals],
                }
            )
        summary = self.aggregate_signals(signals, conflict_threshold=conflict_threshold)
        return {
            "signals": [item.to_dict() for item in signals],
            "blocked": [
                {
                    "symbol": item.symbol,
                    "timeframe": item.timeframe,
                    "strategy_id": item.strategy_id,
                    "strategy_type": item.strategy_type,
                    "action": item.action,
                    "reason": item.block_reason or item.reason,
                    "confidence": item.confidence,
                    "score": item.weighted_score,
                }
                for item in blocked_signals
            ],
            "summary": summary,
            "strategy_results": strategy_results,
        }

    def run_multi_timeframe(
        self,
        market_data: dict[str, dict[str, list[dict[str, Any]]]],
        configs: list[StrategyConfig],
        conflict_threshold: float = 0.15,
        regimes: dict[str, MarketRegime | str] | None = None,
        regime_scores: dict[str, float] | None = None,
        macro_gate: MacroGateDecision | None = None,
        max_positions: int = 2,
        audit_logger: Any | None = None,
    ) -> dict[str, Any]:
        """Run strategies on multiple timeframes and resolve conflicts."""
        from core.audit_trail import AuditLogger, AuditStage, AuditVerdict
        from core.backtest_validation import HigherTimeframeTrend, build_higher_timeframe_trend
        from core.conflict_resolver import ConflictResolver
        from core.correlation_risk import CorrelationCalculator, CorrelationPositionSizer

        all_signals: list[StrategySignal] = []
        strategy_results: list[dict[str, Any]] = []
        audit_logger = audit_logger or AuditLogger()
        audit_trails = []
        trail_by_key: dict[tuple[str, str, str], Any] = {}
        higher_tf_trends: dict[str, HigherTimeframeTrend] = {}
        trend_source = "4h" if "4h" in market_data else "1d" if "1d" in market_data else ""
        if trend_source:
            for symbol, candles in market_data[trend_source].items():
                higher_tf_trends[symbol] = build_higher_timeframe_trend(candles, timeframe=trend_source)

        for config in configs:
            strategy_signals: list[StrategySignal] = []
            if config.enabled:
                for symbol in config.symbols:
                    for timeframe, timeframe_data in market_data.items():
                        candles = timeframe_data.get(symbol, [])
                        effective_config = self._with_higher_tf_trend(config, higher_tf_trends.get(symbol))
                        trail = audit_logger.create_trail(symbol, timeframe, config.strategy_id)
                        trail_by_key[(symbol, timeframe, config.strategy_id)] = trail
                        if macro_gate is not None:
                            audit_logger.log_step(
                                trail,
                                AuditStage.MACRO_GATE,
                                AuditVerdict.FAIL if macro_gate.state == MacroGateState.BLOCK_NEW_RISK else AuditVerdict.PASS,
                                inputs={"score": macro_gate.score},
                                outputs={"state": macro_gate.state.value, "position_size_multiplier": macro_gate.position_size_multiplier},
                                reason=macro_gate.reason,
                            )
                        signal = self.evaluate_strategy_with_regime(
                            effective_config,
                            symbol,
                            candles,
                            regime=(regimes or {}).get(symbol),
                            regime_score=float((regime_scores or {}).get(symbol, 0.0) or 0.0),
                            timeframe=timeframe,
                        )
                        audit_logger.log_step(
                            trail,
                            AuditStage.SIGNAL_GENERATION,
                            AuditVerdict.PASS if signal and signal.action != "HOLD" else AuditVerdict.SKIP,
                            inputs={"strategy_type": config.type, "params": config.parameters, "candles": len(candles)},
                            outputs=signal.to_dict() if signal else {"action": "NONE"},
                            reason="" if signal else "no signal",
                        )
                        if signal:
                            signal = self.apply_macro_gate(signal, macro_gate)
                            audit_logger.log_step(
                                trail,
                                AuditStage.REGIME_FILTER,
                                AuditVerdict.PASS if signal.action != "HOLD" else AuditVerdict.ADJUST,
                                inputs={"regime": str((regimes or {}).get(symbol, "")), "regime_score": signal.regime_score},
                                outputs={"action": signal.action, "confidence": signal.confidence},
                                reason=signal.reason,
                            )
                            strategy_signals.append(signal)
                            all_signals.append(signal)
                            audit_logger.finalize(trail, "PENDING", "awaiting conflict resolution")
                        else:
                            audit_logger.finalize(trail, "SKIPPED", "signal generation returned no actionable signal")
                        audit_trails.append(trail)
            strategy_results.append(
                {
                    "strategy_id": config.strategy_id,
                    "strategy_name": BUILTIN_STRATEGIES[config.type]["name"],
                    "strategy_type": config.type,
                    "enabled": config.enabled,
                    "weight": config.weight,
                    "symbols": config.symbols,
                    "signals": [item.to_dict() for item in strategy_signals],
                }
            )

        resolver = ConflictResolver(max_positions=max_positions)
        result = resolver.resolve(all_signals, higher_tf_trends)
        for item in result.winners:
            trail = trail_by_key.get((item.symbol, item.timeframe, item.strategy_id))
            if trail:
                audit_logger.log_step(
                    trail,
                    AuditStage.CONFLICT_RESOLUTION,
                    AuditVerdict.PASS,
                    inputs={"score": item.score},
                    outputs={"winner": True, "action": item.action},
                    reason=item.reason or "winner",
                )
                audit_logger.finalize(trail, "EXECUTABLE", "selected by conflict resolver")
        for item in result.blocked:
            trail = trail_by_key.get((item.symbol, item.timeframe, item.strategy_id))
            if trail:
                audit_logger.log_step(
                    trail,
                    AuditStage.CONFLICT_RESOLUTION,
                    AuditVerdict.FAIL,
                    inputs={"score": item.score},
                    outputs={"winner": False, "action": item.action},
                    reason=item.reason or result.block_reasons.get(item.symbol, "blocked"),
                )
                audit_logger.finalize(trail, "BLOCKED", item.reason or "blocked by conflict resolver")

        primary_tf = "1h" if "1h" in market_data else next(iter(market_data.keys()), "")
        correlation_adjustments: dict[str, Any] = {}
        if primary_tf:
            corr_matrix = CorrelationCalculator(window=30, min_points=20).compute_matrix(market_data.get(primary_tf, {}))
            adjustments = CorrelationPositionSizer().adjust(
                [
                    {
                        "symbol": item.symbol,
                        "action": item.action,
                        "position_ratio": next((cfg.parameters.get("position_ratio", 0.2) for cfg in configs if cfg.strategy_id == item.strategy_id), 0.2),
                    }
                    for item in result.winners
                ],
                corr_matrix,
            )
            correlation_adjustments = {item.symbol: item for item in adjustments}
            for item in result.winners:
                adj = correlation_adjustments.get(item.symbol)
                trail = trail_by_key.get((item.symbol, item.timeframe, item.strategy_id))
                if trail and adj:
                    audit_logger.log_step(
                        trail,
                        AuditStage.CORRELATION_FILTER,
                        AuditVerdict.ADJUST if adj.multiplier < 1 else AuditVerdict.PASS,
                        inputs={"original_ratio": adj.original_ratio},
                        outputs={"adjusted_ratio": adj.adjusted_ratio, "multiplier": adj.multiplier, "correlated_with": adj.correlated_with},
                        reason=adj.reason,
                    )
        winner_signals = [candidate.signal for candidate in result.winners]
        summary = self.aggregate_signals(winner_signals, conflict_threshold=conflict_threshold)

        return {
            "signals": [item.to_dict() for item in all_signals],
            "winners": [
                {
                    "symbol": item.symbol,
                    "timeframe": item.timeframe,
                    "strategy_id": item.strategy_id,
                    "strategy_type": item.strategy_type,
                    "action": item.action,
                    "reason": item.reason or "winner",
                    "confidence": item.confidence,
                    "score": item.score,
                    "position_multiplier": getattr(correlation_adjustments.get(item.symbol), "multiplier", 1.0),
                    "adjusted_position_ratio": getattr(correlation_adjustments.get(item.symbol), "adjusted_ratio", 0.0),
                }
                for item in result.winners
            ],
            "blocked": [
                {
                    "symbol": item.symbol,
                    "timeframe": item.timeframe,
                    "strategy_id": item.strategy_id,
                    "strategy_type": item.strategy_type,
                    "action": item.action,
                    "reason": item.reason or result.block_reasons.get(item.symbol, "ranked_out"),
                    "confidence": item.confidence,
                    "score": item.score,
                }
                for item in result.blocked
            ],
            "audit_trails": [trail.to_dict() for trail in audit_trails],
            "summary": summary,
            "strategy_results": strategy_results,
        }

    def backtest(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        configs: list[StrategyConfig],
        initial_cash: float = 10000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        min_quantity: float = 0.000001,
        position_sizing: str = "strategy_position_ratio",
        period: str = "1h",
    ) -> list[dict[str, Any]]:
        from core.crypto_backtest_engine import CryptoBacktestEngine

        engine = CryptoBacktestEngine(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            min_quantity=min_quantity,
            position_sizing=position_sizing,
            period=period,
        )
        return engine.run_many(market_data, configs)

    # ------------------------------------------------------------------
    # Parameter grid helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_param_grid(strategy_type: str) -> list[dict[str, Any]]:
        """Return the default parameter grid for one strategy type.

        Each dict in the list is a set of strategy-specific parameter overrides.
        These are designed to test a reasonable range around the defaults.
        """
        strategy_type = str(strategy_type or "").strip().lower()
        grids: dict[str, list[dict[str, Any]]] = {
            "dual_ma": [
                {"fast_period": 5, "slow_period": 20},
                {"fast_period": 7, "slow_period": 25},
                {"fast_period": 10, "slow_period": 30},
                {"fast_period": 12, "slow_period": 26},
                {"fast_period": 15, "slow_period": 40},
            ],
            "rsi": [
                {"period": 14, "oversold": 25, "overbought": 75},
                {"period": 14, "oversold": 30, "overbought": 70},
                {"period": 14, "oversold": 35, "overbought": 65},
                {"period": 21, "oversold": 30, "overbought": 70},
                {"period": 21, "oversold": 25, "overbought": 75},
            ],
            "macd": [
                {"fast_period": 8, "slow_period": 21, "signal_period": 5},
                {"fast_period": 12, "slow_period": 26, "signal_period": 9},
                {"fast_period": 5, "slow_period": 35, "signal_period": 5},
                {"fast_period": 10, "slow_period": 30, "signal_period": 7},
            ],
            "bollinger": [
                {"period": 14, "stddev_multiplier": 2.0},
                {"period": 20, "stddev_multiplier": 2.0},
                {"period": 20, "stddev_multiplier": 2.5},
                {"period": 14, "stddev_multiplier": 2.5},
                {"period": 20, "stddev_multiplier": 1.5},
            ],
            "momentum": [
                {"lookback_period": 10, "buy_threshold": 0.02, "sell_threshold": -0.02},
                {"lookback_period": 10, "buy_threshold": 0.03, "sell_threshold": -0.02},
                {"lookback_period": 10, "buy_threshold": 0.03, "sell_threshold": -0.03},
                {"lookback_period": 20, "buy_threshold": 0.03, "sell_threshold": -0.02},
                {"lookback_period": 20, "buy_threshold": 0.04, "sell_threshold": -0.02},
            ],
        }
        return grids.get(strategy_type, [{}])

    def backtest_with_grid(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        configs: list[StrategyConfig],
        initial_cash: float = 10000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        min_quantity: float = 0.000001,
        period: str = "1h",
        param_grid: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run backtests for each strategy config across its parameter grid.

        For each (config, param_combo) pair this runs an independent backtest
        and returns all results sorted by total_return descending.

        Args:
            market_data: {symbol: [kline_dict]}
            configs: strategy configs to test
            initial_cash: starting USDT balance
            fee_rate: per-trade fee (0.001 = 0.1%)
            param_grid: optional override for all configs; if None, uses
                        build_param_grid() per config type.

        Returns:
            list of backtest result dicts, each augmented with ``params_used``.
        """
        from core.crypto_backtest_engine import CryptoBacktestEngine

        engine = CryptoBacktestEngine(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            min_quantity=min_quantity,
            period=period,
        )
        all_results: list[dict[str, Any]] = []
        for config in configs:
            if not config.enabled:
                continue
            grid = param_grid or self.build_param_grid(config.type)
            if not grid:
                grid = [{}]
            for params in grid:
                merged_params = {**config.parameters, **params}
                trial_config = StrategyConfig(
                    strategy_id=config.strategy_id,
                    type=config.type,
                    symbols=config.symbols,
                    weight=config.weight,
                    enabled=True,
                    parameters=merged_params,
                )
                try:
                    results = engine.run_many(market_data, [trial_config])
                except Exception:
                    continue
                for r in results:
                    r["params_used"] = dict(params)
                all_results.extend(results)

        all_results.sort(key=lambda r: float(r.get("total_return_percent", 0) or 0), reverse=True)
        return all_results

    # ------------------------------------------------------------------
    # Strategy evaluation (per-symbol, per-config)
    # ------------------------------------------------------------------

    def evaluate_strategy(
        self,
        config: StrategyConfig,
        symbol: str,
        candles: list[dict[str, Any]],
        timeframe: str | None = None,
    ) -> StrategySignal | None:
        closes = [self._float(row.get("close", row.get("price"))) for row in candles if self._float(row.get("close", row.get("price"))) > 0]
        if not closes:
            return None
        strategy_type = config.type
        if strategy_type == "dual_ma":
            result = self._dual_ma(closes, config.parameters)
        elif strategy_type == "rsi":
            result = self._rsi(closes, config.parameters)
        elif strategy_type == "macd":
            result = self._macd(closes, config.parameters)
        elif strategy_type == "bollinger":
            result = self._bollinger(closes, config.parameters)
        elif strategy_type == "momentum":
            result = self._momentum(closes, config.parameters)
        else:
            result = None
        if not result:
            return None

        signal_timeframe = str(timeframe or candles[-1].get("period") or "1h")
        action = str(result["action"]).upper()
        confidence = max(0.0, min(float(result.get("confidence", 0.0)), 1.0))
        score = confidence * config.weight * (1 if action == "BUY" else -1 if action == "SELL" else 0)
        return StrategySignal(
            strategy_id=config.strategy_id,
            strategy_name=BUILTIN_STRATEGIES[strategy_type]["name"],
            strategy_type=strategy_type,
            symbol=symbol,
            action=action,
            price=closes[-1],
            confidence=confidence,
            weight=config.weight,
            weighted_score=score,
            reason=str(result.get("reason") or ""),
            timestamp=datetime.now().isoformat(),
            timeframe=signal_timeframe,
            indicators={key: self._float(value) for key, value in (result.get("indicators") or {}).items()},
        )

    def evaluate_strategy_with_regime(
        self,
        config: StrategyConfig,
        symbol: str,
        candles: list[dict[str, Any]],
        regime: MarketRegime | str | None = None,
        regime_score: float = 0.0,
        timeframe: str | None = None,
    ) -> StrategySignal | None:
        """Evaluate a strategy and apply optional market-regime compatibility rules."""
        signal = self.evaluate_strategy(config, symbol, candles, timeframe=timeframe)
        if signal is None:
            return signal

        signal.regime_score = self._float(regime_score)
        signal.indicators["regime_score"] = self._float(regime_score)
        if regime is None:
            return signal

        market_regime = self._normalize_regime(regime)
        if market_regime is None or market_regime == MarketRegime.UNKNOWN:
            return signal

        if market_regime == MarketRegime.RISK_OFF:
            signal.action = "HOLD"
            signal.confidence = max(0.0, signal.confidence - 0.85)
            signal.weighted_score = 0.0
            signal.reason = f"RISK_OFF: {signal.reason}"
            return signal

        allowed = self.REGIME_STRATEGY_COMPAT.get(config.type, set())
        if allowed and market_regime not in allowed:
            signal.action = "HOLD"
            signal.confidence = max(0.0, signal.confidence - 0.6)
            signal.weighted_score = 0.0
            signal.reason = f"regime({market_regime.value})_blocked: {signal.reason}"
        return signal

    def apply_macro_gate(self, signal: StrategySignal, macro_gate: MacroGateDecision | None = None) -> StrategySignal:
        """Apply optional macro gate penalties to a simulated signal."""
        if macro_gate is None:
            return signal

        signal.indicators["macro_score"] = self._float(macro_gate.score)
        signal.indicators["macro_position_multiplier"] = self._float(macro_gate.position_size_multiplier)
        signal.macro_gate_state = macro_gate.state.value
        if macro_gate.state == MacroGateState.BLOCK_NEW_RISK and signal.action == "BUY":
            signal.blocked = True
            signal.block_reason = macro_gate.reason
            signal.action = "HOLD"
            signal.confidence = 0.0
            signal.weighted_score = 0.0
            signal.reason = f"[Macro BLOCK] {signal.reason}"
            return signal

        if macro_gate.state == MacroGateState.ALLOW_REDUCED and signal.action in {"BUY", "SELL"}:
            penalty = max(0.0, min(float(macro_gate.confidence_penalty or 0) / 100.0, 1.0))
            signal.confidence = max(0.0, signal.confidence - penalty)
            direction = 1 if signal.action == "BUY" else -1
            signal.weighted_score = signal.confidence * signal.weight * direction * macro_gate.position_size_multiplier
            signal.reason = f"[Macro REDUCED] {signal.reason}"
        return signal

    def _with_higher_tf_trend(self, config: StrategyConfig, trend: Any | None) -> StrategyConfig:
        if config.type != "bollinger" or trend is None:
            return config
        return StrategyConfig(
            strategy_id=config.strategy_id,
            type=config.type,
            symbols=config.symbols,
            weight=config.weight,
            enabled=config.enabled,
            parameters={**config.parameters, "higher_tf_trend": self._trend_payload(trend)},
        )

    def _trend_payload(self, trend: Any) -> dict[str, Any]:
        if isinstance(trend, dict):
            return dict(trend)
        return {
            "direction": str(getattr(trend, "direction", "neutral") or "neutral"),
            "four_hour_change_pct": self._float(getattr(trend, "four_hour_change_pct", 0.0)),
            "daily_change_pct": self._float(getattr(trend, "daily_change_pct", 0.0)),
        }

    def aggregate_signals(self, signals: list[StrategySignal], conflict_threshold: float = 0.15) -> list[dict[str, Any]]:
        by_symbol: dict[str, list[StrategySignal]] = {}
        for signal in signals:
            by_symbol.setdefault(signal.symbol, []).append(signal)

        summary: list[dict[str, Any]] = []
        for symbol, items in sorted(by_symbol.items()):
            buy_score = sum(max(item.weighted_score, 0.0) for item in items)
            sell_score = abs(sum(min(item.weighted_score, 0.0) for item in items))
            hold_count = sum(1 for item in items if item.action == "HOLD")
            blocked_count = sum(1 for item in items if item.blocked)
            conflict = buy_score > 0 and sell_score > 0
            net_score = buy_score - sell_score
            threshold = max(float(conflict_threshold or 0), 0.0)
            if blocked_count and buy_score <= 0 and sell_score <= 0:
                action = "HOLD"
                reason = "blocked by macro or risk gate"
            elif abs(net_score) <= threshold:
                action = "HOLD"
                reason = "signal conflict or insufficient weighted edge"
            elif net_score > 0:
                action = "BUY"
                reason = "buy score dominates"
            else:
                action = "SELL"
                reason = "sell score dominates"
            summary.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "net_score": net_score,
                    "buy_score": buy_score,
                    "sell_score": sell_score,
                    "hold_count": hold_count,
                    "conflict": conflict,
                    "reason": reason,
                    "signal_count": len(items),
                    "source_strategy_ids": [item.strategy_id for item in items],
                    "price": items[-1].price if items else 0.0,
                }
            )
        return summary

    def _dual_ma(self, closes: list[float], params: dict[str, Any]) -> dict[str, Any] | None:
        fast = max(int(params.get("fast_period", 12) or 12), 1)
        slow = max(int(params.get("slow_period", 26) or 26), fast + 1)
        if len(closes) < slow + 1:
            return None
        fast_now = fmean(closes[-fast:])
        slow_now = fmean(closes[-slow:])
        fast_prev = fmean(closes[-fast - 1 : -1])
        slow_prev = fmean(closes[-slow - 1 : -1])
        if fast_prev <= slow_prev and fast_now > slow_now:
            action = "BUY"
            reason = f"{fast}/{slow} moving-average golden cross"
        elif fast_prev >= slow_prev and fast_now < slow_now:
            action = "SELL"
            reason = f"{fast}/{slow} moving-average death cross"
        else:
            action = "HOLD"
            reason = "moving averages have not crossed"
        confidence = min(abs(fast_now - slow_now) / max(slow_now, 1.0) * 20 + 0.25, 1.0)
        return {"action": action, "confidence": confidence, "reason": reason, "indicators": {"fast_ma": fast_now, "slow_ma": slow_now}}

    def _rsi(self, closes: list[float], params: dict[str, Any]) -> dict[str, Any] | None:
        period = max(int(params.get("period", params.get("rsi_period", 14)) or 14), 1)
        if len(closes) < period + 1:
            return None
        rsi = self._rsi_value(closes, period)
        oversold = float(params.get("oversold", 30) or 30)
        overbought = float(params.get("overbought", 70) or 70)
        if rsi <= oversold:
            action = "BUY"
            reason = f"RSI oversold {rsi:.2f}"
            confidence = min((oversold - rsi) / max(oversold, 1.0) + 0.35, 1.0)
        elif rsi >= overbought:
            action = "SELL"
            reason = f"RSI overbought {rsi:.2f}"
            confidence = min((rsi - overbought) / max(100 - overbought, 1.0) + 0.35, 1.0)
        else:
            action = "HOLD"
            reason = f"RSI neutral {rsi:.2f}"
            confidence = 0.2
        return {"action": action, "confidence": confidence, "reason": reason, "indicators": {"rsi": rsi}}

    def _macd(self, closes: list[float], params: dict[str, Any]) -> dict[str, Any] | None:
        fast = max(int(params.get("fast_period", 12) or 12), 1)
        slow = max(int(params.get("slow_period", 26) or 26), fast + 1)
        signal_period = max(int(params.get("signal_period", 9) or 9), 1)
        if len(closes) < slow + signal_period + 2:
            return None
        ema_fast = self._ema_series(closes, fast)
        ema_slow = self._ema_series(closes, slow)
        dif = [a - b for a, b in zip(ema_fast, ema_slow)]
        dea = self._ema_series(dif, signal_period)
        macd_now = dif[-1] - dea[-1]
        macd_prev = dif[-2] - dea[-2]
        if macd_prev <= 0 < macd_now:
            action = "BUY"
            reason = "MACD bullish cross"
        elif macd_prev >= 0 > macd_now:
            action = "SELL"
            reason = "MACD bearish cross"
        else:
            action = "HOLD"
            reason = "MACD has not crossed"
        confidence = min(abs(macd_now) / max(closes[-1], 1.0) * 100 + 0.25, 1.0)
        return {"action": action, "confidence": confidence, "reason": reason, "indicators": {"dif": dif[-1], "dea": dea[-1], "macd": macd_now}}

    def _bollinger(self, closes: list[float], params: dict[str, Any]) -> dict[str, Any] | None:
        period = max(int(params.get("period", 20) or 20), 2)
        multiplier = max(float(params.get("stddev_multiplier", 2.0) or 2.0), 0.1)
        if len(closes) < period:
            return None
        window = closes[-period:]
        middle = fmean(window)
        deviation = pstdev(window)
        upper = middle + multiplier * deviation
        lower = middle - multiplier * deviation
        price = closes[-1]
        if deviation <= 0:
            return {"action": "HOLD", "confidence": 0.1, "reason": "bollinger band has no volatility", "indicators": {"middle": middle, "upper": upper, "lower": lower}}

        higher_tf_trend = self._trend_payload(params.get("higher_tf_trend") or {})
        higher_tf_direction = str(higher_tf_trend.get("direction") or "neutral").lower()
        trend_filter_enabled = bool(params.get("use_higher_tf_trend_filter", True))
        if price <= lower:
            action = "BUY"
            reason = "price touched lower Bollinger band"
            if trend_filter_enabled and higher_tf_direction in {"down", "trend_down", "bear", "bearish", "risk_off"}:
                action = "HOLD"
                reason = "higher timeframe downtrend blocks Bollinger mean-reversion long"
        elif price >= upper:
            action = "SELL"
            reason = "price touched upper Bollinger band"
        else:
            action = "HOLD"
            reason = "price is inside Bollinger bands"
        confidence = min(abs(price - middle) / max(upper - lower, 1.0) * 2 + 0.2, 1.0)
        if action == "HOLD" and "higher timeframe" in reason:
            confidence = min(confidence, 0.15)
        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "indicators": {
                "middle": middle,
                "upper": upper,
                "lower": lower,
                "higher_tf_4h_change_pct": self._float(higher_tf_trend.get("four_hour_change_pct")),
                "higher_tf_daily_change_pct": self._float(higher_tf_trend.get("daily_change_pct")),
            },
        }

    def _momentum(self, closes: list[float], params: dict[str, Any]) -> dict[str, Any] | None:
        lookback = max(int(params.get("lookback_period", params.get("period", 20)) or 20), 1)
        if len(closes) <= lookback:
            return None
        base = closes[-lookback - 1]
        if base <= 0:
            return None
        momentum = (closes[-1] - base) / base
        buy_threshold = float(params.get("buy_threshold", 0.03) or 0.03)
        sell_threshold = float(params.get("sell_threshold", -0.02) or -0.02)
        if momentum >= buy_threshold:
            action = "BUY"
            reason = f"momentum breakout up {momentum:.2%}"
        elif momentum <= sell_threshold:
            action = "SELL"
            reason = f"momentum breakdown {momentum:.2%}"
        else:
            action = "HOLD"
            reason = f"momentum below threshold {momentum:.2%}"
        confidence = min(abs(momentum) / max(abs(buy_threshold), abs(sell_threshold), 0.01) * 0.6 + 0.2, 1.0)
        return {"action": action, "confidence": confidence, "reason": reason, "indicators": {"momentum": momentum}}

    def _rsi_value(self, closes: list[float], period: int) -> float:
        gains = []
        losses = []
        for left, right in zip(closes[-period - 1 : -1], closes[-period:]):
            delta = right - left
            gains.append(max(delta, 0.0))
            losses.append(abs(min(delta, 0.0)))
        avg_gain = fmean(gains) if gains else 0.0
        avg_loss = fmean(losses) if losses else 0.0
        if avg_loss <= 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _ema_series(self, values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        ema = [float(values[0])]
        for value in values[1:]:
            ema.append(float(value) * alpha + ema[-1] * (1 - alpha))
        return ema

    def _max_drawdown(self, equity_values: list[float]) -> float:
        if not equity_values:
            return 0.0
        peak = equity_values[0]
        drawdown = 0.0
        for value in equity_values:
            peak = max(peak, value)
            if peak > 0:
                drawdown = max(drawdown, (peak - value) / peak)
        return drawdown

    def _equity_returns(self, equity_values: list[float]) -> list[float]:
        returns = []
        for previous, current in zip(equity_values, equity_values[1:]):
            if previous > 0:
                returns.append((current - previous) / previous)
        return returns

    def _sharpe(self, returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        volatility = pstdev(returns)
        if volatility <= 0:
            return 0.0
        return fmean(returns) / volatility * sqrt(365)

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _normalize_regime(self, value: MarketRegime | str | None) -> MarketRegime | None:
        if value is None:
            return None
        if isinstance(value, MarketRegime):
            return value
        try:
            return MarketRegime(str(value).strip().upper())
        except ValueError:
            return None
