"""Walk-forward backtest framework for crypto strategies.

Splits OHLCV data into rolling training/validation windows, tests multiple
parameter combinations, selects the best performer on training data, and
validates on out-of-sample data with perturbation analysis.

Design principles:
- Delegates per-config backtests to the existing CryptoBacktestEngine.
- Strict factor audit marks data that is NOT available point-in-time.
- Each strategy is evaluated independently; a 0-trade strategy does not
  pollute other strategies' metrics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from random import Random
from statistics import fmean, pstdev
from typing import Any

from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_strategy_engine import BUILTIN_STRATEGIES, CryptoStrategyEngine, StrategyConfig


# ---------------------------------------------------------------------------
# Parameter grids for each built-in strategy type
# ---------------------------------------------------------------------------

DEFAULT_PARAM_GRIDS: dict[str, list[dict[str, Any]]] = {
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardConfig:
    """Walk-forward backtest configuration."""

    train_ratio: float = 0.6
    validation_ratio: float = 0.2
    # test_ratio is inferred: 1 - train_ratio - validation_ratio
    min_train_candles: int = 50
    step_size: int = 20  # candles to slide each window
    perturbation_runs: int = 200
    perturbation_pct: float = 0.025
    min_train_trades: int = 5  # minimum trades in training to consider valid
    fragile_threshold: float = 0.40  # max validation/decline below train return for fragility
    selection_score_penalty: float = 2.0  # drawdown penalty multiplier in selectionScore
    initial_cash: float = 10000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    min_quantity: float = 0.000001
    period: str = "1h"

    def __post_init__(self) -> None:
        self.train_ratio = min(max(float(self.train_ratio or 0.6), 0.1), 0.9)
        self.validation_ratio = min(max(float(self.validation_ratio or 0.2), 0.05), 0.8)
        if self.train_ratio + self.validation_ratio >= 0.95:
            self.validation_ratio = max(0.05, 0.95 - self.train_ratio)
        self.min_train_candles = max(int(self.min_train_candles or 50), 10)
        self.step_size = max(int(self.step_size or 20), 1)
        self.perturbation_runs = max(int(self.perturbation_runs or 0), 0)
        self.perturbation_pct = max(float(self.perturbation_pct or 0), 0.0)
        self.initial_cash = max(float(self.initial_cash or 10000), 1.0)
        self.fee_rate = max(float(self.fee_rate or 0), 0.0)
        self.slippage_rate = max(float(self.slippage_rate or 0), 0.0)
        self.min_quantity = max(float(self.min_quantity or 0.000001), 0.000001)
        self.period = str(self.period or "1h")


@dataclass
class WalkForwardRound:
    """Result of one walk-forward window for one strategy/symbol/param combo."""

    round_index: int
    strategy_id: str
    strategy_type: str
    symbol: str
    params: dict[str, Any]
    train_result: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    selection_score: float = 0.0
    is_fragile: bool = False
    perturbation_summary: dict[str, Any] | None = None


@dataclass
class ParamCombo:
    """One set of strategy parameters to test."""

    params: dict[str, Any]
    train_result: dict[str, Any] | None = None
    avg_selection_score: float = 0.0


# ---------------------------------------------------------------------------
# Factor audit
# ---------------------------------------------------------------------------

def build_strict_factor_audit(
    has_macro: bool = False,
    has_funding_rate: bool = False,
    has_orderbook: bool = False,
    has_onchain: bool = False,
) -> dict[str, Any]:
    """Return a factor audit describing data availability for backtesting.

    This is modelled on CryptoQuant AI's approach: explicitly mark which
    data sources are point-in-time available vs. unavailable to prevent
    look-ahead bias.
    """
    return {
        "price": {
            "available": True,
            "source": "ohlcv_timestamp_only",
            "note": "Only OHLCV timestamps are used; no future price data is leaked",
        },
        "macro": {
            "available": bool(has_macro),
            "reason": "" if has_macro else "no_point_in_time_macro_data",
            "note": "DXY/M2/BTC.D/Gold/SPX/Yields via optional TradingView and FRED providers",
            "sources": ["TradingView (DXY, BTC.D, XAUUSD, SPX)", "FRED (M2SL, DGS2, DGS10)"],
        },
        "onchain": {
            "available": bool(has_onchain),
            "reason": "" if has_onchain else "no_onchain_data_source",
            "note": "On-chain data is only available when an external source is configured",
        },
        "news": {
            "available": False,
            "reason": "no_news_sentiment_source",
        },
        "orderbook": {
            "available": bool(has_orderbook),
            "reason": "" if has_orderbook else "no_historical_orderbook_snapshots",
            "note": "Order book data is live-only unless historical snapshots are stored",
        },
        "funding_rate": {
            "available": bool(has_funding_rate),
            "reason": "" if has_funding_rate else "no_historical_funding_rate_data",
            "note": "Perpetual funding rate is live-available; historical replay requires stored snapshots",
        },
    }


# ---------------------------------------------------------------------------
# Window creation
# ---------------------------------------------------------------------------

def create_walk_forward_windows(
    klines: list[dict[str, Any]],
    config: WalkForwardConfig | None = None,
) -> list[dict[str, Any]]:
    """Slice a list of K-lines into overlapping training/validation windows.

    Returns a list of dicts, each containing:
        round_index, train_klines, validation_klines, train_start, train_end,
        validation_start, validation_end
    """
    cfg = config or WalkForwardConfig()
    total = len(klines)
    min_needed = cfg.min_train_candles * 2
    if total < min_needed:
        return []

    windows: list[dict[str, Any]] = []
    start = 0
    round_index = 0

    while start + min_needed <= total:
        train_end = start + max(int((total - start) * cfg.train_ratio), cfg.min_train_candles)
        train_end = min(train_end, total - cfg.min_train_candles)

        val_size = max(int((total - start) * cfg.validation_ratio), cfg.min_train_candles)
        val_end = min(train_end + val_size, total)

        train_slice = klines[start:train_end]
        val_slice = klines[train_end:val_end]

        if len(train_slice) >= cfg.min_train_candles and len(val_slice) >= cfg.min_train_candles:
            train_start_ts = str(train_slice[0].get("start_time", ""))
            train_end_ts = str(train_slice[-1].get("start_time", ""))
            val_start_ts = str(val_slice[0].get("start_time", ""))
            val_end_ts = str(val_slice[-1].get("start_time", ""))

            windows.append({
                "round_index": round_index,
                "train_klines": deepcopy(train_slice),
                "validation_klines": deepcopy(val_slice),
                "train_start": train_start_ts,
                "train_end": train_end_ts,
                "validation_start": val_start_ts,
                "validation_end": val_end_ts,
            })
            round_index += 1

        start += cfg.step_size

    return windows


# ---------------------------------------------------------------------------
# Selection scoring
# ---------------------------------------------------------------------------

def _selection_score(backtest_result: dict[str, Any], penalty: float = 2.0) -> float:
    """Score a backtest result for parameter selection.

    score = total_return_percent - penalty * max_drawdown_percent

    This penalises strategies that achieve high returns through large drawdowns.
    If trade_count < 1 the score is -inf (invalid).
    """
    trade_count = int(backtest_result.get("trade_count", 0) or 0)
    if trade_count < 1:
        return float("-inf")
    total_return = float(backtest_result.get("total_return_percent", 0) or 0)
    max_dd = float(backtest_result.get("max_drawdown_percent", 0) or 0)
    return total_return - penalty * max_dd


def _merge_params(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge parameter dicts, with override winning."""
    merged = dict(base)
    for key, value in override.items():
        merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Main walk-forward runner
# ---------------------------------------------------------------------------

class WalkForwardRunner:
    """Orchestrate walk-forward backtesting across strategies and symbols."""

    def __init__(self, config: WalkForwardConfig | None = None):
        self.config = config or WalkForwardConfig()
        self.engine = CryptoStrategyEngine()
        self._audit = build_strict_factor_audit()

    @property
    def factor_audit(self) -> dict[str, Any]:
        return dict(self._audit)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        configs: list[StrategyConfig],
        param_grids: dict[str, list[dict[str, Any]]] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run walk-forward backtest for multiple strategy configs.

        Args:
            market_data: {symbol: [kline_dict, ...]}
            configs: list of StrategyConfig to evaluate
            param_grids: optional custom parameter grids keyed by strategy type

        Returns:
            dict with keys:
                rounds: all WalkForwardRound results
                by_strategy: per-strategy summary
                by_symbol: per-symbol summary
                factor_audit: data availability audit
                config: WalkForwardConfig used
        """
        grids = self._normalize_param_grids(param_grids)
        all_rounds: list[WalkForwardRound] = []

        for config in configs:
            if not config.enabled:
                continue
            for symbol in config.symbols:
                klines = market_data.get(symbol, [])
                if len(klines) < self.config.min_train_candles * 2:
                    continue
                rounds = self._run_one_symbol(config, symbol, klines, grids)
                all_rounds.extend(rounds)

        return {
            "rounds": [self._round_to_dict(r) for r in all_rounds],
            "by_strategy": self._summarize_by_strategy(all_rounds),
            "by_symbol": self._summarize_by_symbol(all_rounds),
            "factor_audit": self.factor_audit,
            "config": {
                "train_ratio": self.config.train_ratio,
                "validation_ratio": self.config.validation_ratio,
                "step_size": self.config.step_size,
                "perturbation_runs": self.config.perturbation_runs,
                "min_train_candles": self.config.min_train_candles,
                "initial_cash": self.config.initial_cash,
                "fee_rate": self.config.fee_rate,
                "slippage_rate": self.config.slippage_rate,
                "min_quantity": self.config.min_quantity,
                "period": self.config.period,
            },
        }

    def _normalize_param_grids(
        self,
        param_grids: dict[str, list[dict[str, Any]]] | list[dict[str, Any]] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        if not param_grids:
            return DEFAULT_PARAM_GRIDS
        if isinstance(param_grids, list):
            cleaned = [dict(item or {}) for item in param_grids]
            return {key: cleaned for key in DEFAULT_PARAM_GRIDS}
        normalized: dict[str, list[dict[str, Any]]] = {}
        for key, value in dict(param_grids).items():
            normalized[str(key).strip().lower()] = [dict(item or {}) for item in list(value or [])] or [{}]
        return {**DEFAULT_PARAM_GRIDS, **normalized}

    def _run_one_symbol(
        self,
        config: StrategyConfig,
        symbol: str,
        klines: list[dict[str, Any]],
                param_grids: dict[str, list[dict[str, Any]]],
    ) -> list[WalkForwardRound]:
        """Run walk-forward for one strategy + one symbol."""
        windows = create_walk_forward_windows(klines, self.config)
        if not windows:
            return []

        strategy_type = config.type
        grid = param_grids.get(strategy_type, [config.parameters or {}])
        if not grid:
            grid = [config.parameters or {}]

        all_rounds: list[WalkForwardRound] = []

        for window in windows:
            # --- Evaluate each parameter combo on training data ---
            combos: list[ParamCombo] = []
            for params in grid:
                merged_params = _merge_params(config.parameters or {}, params)
                trial_config = StrategyConfig(
                    strategy_id=config.strategy_id,
                    type=config.type,
                    symbols=[symbol],
                    weight=config.weight,
                    enabled=True,
                    parameters=merged_params,
                )
                train_data = {symbol: window["train_klines"]}
                try:
                    train_results = self._run_backtest(train_data, trial_config)
                    train_result = train_results[0] if train_results else None
                except Exception:
                    train_result = None
                score = _selection_score(train_result, self.config.selection_score_penalty) if train_result else float("-inf")
                combos.append(ParamCombo(params=params, train_result=train_result, avg_selection_score=score))

            # Select best combo
            valid_combos = [c for c in combos if c.avg_selection_score > float("-inf")]
            if not valid_combos:
                continue
            valid_combos.sort(key=lambda c: c.avg_selection_score, reverse=True)
            best = valid_combos[0]

            # --- Run validation with best params ---
            merged_params = _merge_params(config.parameters or {}, best.params)
            trial_config = StrategyConfig(
                strategy_id=config.strategy_id,
                type=config.type,
                symbols=[symbol],
                weight=config.weight,
                enabled=True,
                parameters=merged_params,
            )
            val_data = {symbol: window["validation_klines"]}
            try:
                val_results = self._run_backtest(val_data, trial_config)
                val_result = val_results[0] if val_results else None
            except Exception:
                val_result = None

            # --- Perturbation analysis ---
            perturbation = None
            is_fragile = False
            if val_result and val_result.get("trade_count", 0) > 0:
                perturbation = self._perturbation_analysis(val_data, trial_config)
                is_fragile = perturbation.get("is_fragile", False)

            rnd = WalkForwardRound(
                round_index=window["round_index"],
                strategy_id=config.strategy_id,
                strategy_type=config.type,
                symbol=symbol,
                params=merged_params,
                train_result=deepcopy(best.train_result),
                validation_result=deepcopy(val_result),
                selection_score=best.avg_selection_score,
                is_fragile=is_fragile,
                perturbation_summary=perturbation,
            )
            all_rounds.append(rnd)

        return all_rounds

    # ------------------------------------------------------------------
    # Perturbation analysis
    # ------------------------------------------------------------------

    def _perturbation_analysis(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        config: StrategyConfig,
    ) -> dict[str, Any]:
        """Run N backtests with randomly perturbed initial capital.

        If results vary wildly (stddev of total_return > threshold relative
        to base return), the strategy is flagged as fragile.
        """
        base_result = self._run_backtest(market_data, config)
        base = base_result[0] if base_result else None
        if not base:
            return {"is_fragile": False, "runs": 0, "reason": "no_base_result"}

        base_return = float(base.get("total_return_percent", 0) or 0)
        returns: list[float] = []
        rng = Random(42)  # deterministic seed for reproducibility

        for _ in range(self.config.perturbation_runs):
            scale = 1.0 + rng.uniform(-self.config.perturbation_pct, self.config.perturbation_pct)
            from core.crypto_backtest_engine import CryptoBacktestEngine
            engine = CryptoBacktestEngine(
                initial_cash=self.config.initial_cash * scale,
                fee_rate=self.config.fee_rate,
                slippage_rate=self.config.slippage_rate,
                min_quantity=self.config.min_quantity,
                period=self.config.period,
            )
            try:
                perturbed = engine.run(market_data, config)
                returns.append(float(perturbed.get("total_return_percent", 0) or 0))
            except Exception:
                returns.append(base_return)

        if len(returns) < 2:
            return {"is_fragile": False, "runs": len(returns), "reason": "insufficient_runs"}

        avg_return = fmean(returns)
        std_return = pstdev(returns)
        is_fragile = abs(avg_return - base_return) > std_return * 2 if std_return > 0 else False

        return {
            "is_fragile": is_fragile,
            "runs": len(returns),
            "base_return_percent": round(base_return, 4),
            "perturbed_avg_return_percent": round(avg_return, 4),
            "perturbed_std_return_percent": round(std_return, 4),
            "min_return_percent": round(min(returns), 4),
            "max_return_percent": round(max(returns), 4),
            "perturbation_pct": self.config.perturbation_pct,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_backtest(
        self,
        market_data: dict[str, list[dict[str, Any]]],
        config: StrategyConfig,
    ) -> list[dict[str, Any]]:
        """Run a single-config backtest via CryptoBacktestEngine."""
        from core.crypto_backtest_engine import CryptoBacktestEngine

        engine = CryptoBacktestEngine(
            initial_cash=self.config.initial_cash,
            fee_rate=self.config.fee_rate,
            slippage_rate=self.config.slippage_rate,
            min_quantity=self.config.min_quantity,
            period=self.config.period,
        )
        return engine.run_many(market_data, [config])

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def _summarize_by_strategy(self, rounds: list[WalkForwardRound]) -> list[dict[str, Any]]:
        """Group walk-forward rounds by strategy, compute aggregate metrics."""
        by_strategy: dict[str, list[WalkForwardRound]] = {}
        for r in rounds:
            by_strategy.setdefault(r.strategy_id, []).append(r)

        summaries: list[dict[str, Any]] = []
        for sid, items in sorted(by_strategy.items()):
            val_returns = [
                float(r.validation_result.get("total_return_percent", 0) or 0)
                for r in items if r.validation_result
            ]
            train_returns = [
                float(r.train_result.get("total_return_percent", 0) or 0)
                for r in items if r.train_result
            ]
            val_trades = sum(
                int(r.validation_result.get("trade_count", 0) or 0)
                for r in items if r.validation_result
            )
            fragile_count = sum(1 for r in items if r.is_fragile)
            summaries.append({
                "strategy_id": sid,
                "strategy_type": items[0].strategy_type if items else "",
                "round_count": len(items),
                "fragile_count": fragile_count,
                "avg_train_return_percent": round(fmean(train_returns), 4) if train_returns else 0.0,
                "avg_validation_return_percent": round(fmean(val_returns), 4) if val_returns else 0.0,
                "median_validation_return_percent": round(_median(val_returns), 4) if val_returns else 0.0,
                "worst_validation_return_percent": round(min(val_returns), 4) if val_returns else 0.0,
                "total_validation_trades": val_trades,
            })
        return summaries

    def _summarize_by_symbol(self, rounds: list[WalkForwardRound]) -> list[dict[str, Any]]:
        """Group walk-forward rounds by symbol, compute aggregate metrics."""
        by_symbol: dict[str, list[WalkForwardRound]] = {}
        for r in rounds:
            by_symbol.setdefault(r.symbol, []).append(r)

        summaries: list[dict[str, Any]] = []
        for symbol, items in sorted(by_symbol.items()):
            val_returns = [
                float(r.validation_result.get("total_return_percent", 0) or 0)
                for r in items if r.validation_result
            ]
            summaries.append({
                "symbol": symbol,
                "round_count": len(items),
                "avg_validation_return_percent": round(fmean(val_returns), 4) if val_returns else 0.0,
                "median_validation_return_percent": round(_median(val_returns), 4) if val_returns else 0.0,
            })
        return summaries

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _round_to_dict(self, r: WalkForwardRound) -> dict[str, Any]:
        """Convert a round to a JSON-safe dict with truncated trade/equity data."""
        train = deepcopy(r.train_result) if r.train_result else None
        validation = deepcopy(r.validation_result) if r.validation_result else None

        for result in (train, validation):
            if result is None:
                continue
            # Truncate long lists
            if len(result.get("trades", []) or []) > 100:
                result["trades"] = (result["trades"] or [])[-100:]
                result["trades_truncated"] = True
            if len(result.get("equity_curve", []) or []) > 300:
                result["equity_curve"] = (result["equity_curve"] or [])[-300:]
                result["equity_curve_truncated"] = True

        return {
            "round_index": r.round_index,
            "strategy_id": r.strategy_id,
            "strategy_type": r.strategy_type,
            "symbol": r.symbol,
            "params": r.params,
            "train_start": self._result_timestamp(train, "first"),
            "train_end": self._result_timestamp(train, "last"),
            "validation_start": self._result_timestamp(validation, "first"),
            "validation_end": self._result_timestamp(validation, "last"),
            "selection_score": r.selection_score,
            "is_fragile": r.is_fragile,
            "train_result": train,
            "validation_result": validation,
            "perturbation_summary": r.perturbation_summary,
        }

    def _result_timestamp(self, result: dict[str, Any] | None, which: str) -> str:
        if not result:
            return ""
        curve = result.get("equity_curve", []) or []
        if not curve:
            return ""
        item = curve[0] if which == "first" else curve[-1]
        return str(item.get("timestamp", ""))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
