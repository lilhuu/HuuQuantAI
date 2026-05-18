"""Crypto-only parameter optimization utilities."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import random
from typing import Any, Dict, Iterable, List

from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_market_data_provider import normalize_crypto_symbol
from core.crypto_strategy_engine import CryptoStrategyEngine


@dataclass
class OptimizationCandidate:
    parameters: Dict[str, Any]
    score: float
    metrics: Dict[str, Any]


class CryptoStrategyParameterOptimizer:
    """Run grid, random, or lightweight adaptive search with crypto backtests."""

    SUPPORTED_OBJECTIVES = {
        "sharpe_ratio",
        "total_return_percent",
        "max_drawdown_percent",
        "calmar_ratio",
        "win_rate",
        "profit_factor",
    }

    def optimize(
        self,
        strategy_type: str,
        base_config: Dict[str, Any],
        history,
        parameter_grid: Dict[str, list[Any]],
        *,
        objective: str = "sharpe_ratio",
        top_n: int = 5,
        search_method: str = "grid",
        max_evaluations: int = 200,
        random_seed: int = 42,
        period: str = "1h",
        initial_cash: float = 10000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        min_quantity: float = 0.000001,
    ) -> List[OptimizationCandidate]:
        rows = self._normalize_history(history, period=period)
        if not rows:
            return []

        normalized_objective = str(objective or "sharpe_ratio").strip().lower()
        if normalized_objective not in self.SUPPORTED_OBJECTIVES:
            normalized_objective = "sharpe_ratio"

        symbol = self._config_symbol(base_config, rows)
        market_data = {symbol: [row for row in rows if row["symbol"] == symbol]}
        if not market_data[symbol]:
            market_data = {symbol: rows}
        engine = CryptoBacktestEngine(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            min_quantity=min_quantity,
            period=period,
        )
        strategy_engine = CryptoStrategyEngine()
        candidates: List[OptimizationCandidate] = []
        for parameters in self._iter_candidates(
            parameter_grid,
            search_method=search_method,
            max_evaluations=max_evaluations,
            random_seed=random_seed,
        ):
            raw_config = self._build_config(strategy_type, base_config, parameters, symbol)
            try:
                config = strategy_engine.normalize_configs([raw_config], [symbol])[0]
                result = engine.run(market_data, config)
                score = self._score(result, normalized_objective)
                metrics = result
            except Exception as exc:
                score = float("-inf")
                metrics = {"error": str(exc), "symbol": symbol}
            candidates.append(OptimizationCandidate(parameters=parameters, score=score, metrics=metrics))

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[: max(1, int(top_n or 5))]

    def _build_config(
        self,
        strategy_type: str,
        base_config: Dict[str, Any],
        parameters: Dict[str, Any],
        symbol: str,
    ) -> Dict[str, Any]:
        base = dict(base_config or {})
        base_parameters = dict(base.get("parameters") or {})
        base_parameters.update(parameters)
        return {
            "strategy_id": str(base.get("strategy_id") or f"{strategy_type}_optimizer"),
            "type": str(base.get("type") or strategy_type or "dual_ma"),
            "symbols": [symbol],
            "weight": float(base.get("weight", 1.0) or 1.0),
            "enabled": bool(base.get("enabled", True)),
            "parameters": base_parameters,
        }

    def _config_symbol(self, base_config: Dict[str, Any], rows: list[Dict[str, Any]]) -> str:
        raw_symbols = (base_config or {}).get("symbols") or []
        if isinstance(raw_symbols, str):
            raw_symbols = [raw_symbols]
        for item in raw_symbols:
            symbol = normalize_crypto_symbol(item)
            if symbol:
                return symbol
        return rows[0]["symbol"]

    def _iter_candidates(
        self,
        parameter_grid: Dict[str, list[Any]],
        *,
        search_method: str = "grid",
        max_evaluations: int = 200,
        random_seed: int = 42,
    ) -> Iterable[Dict[str, Any]]:
        combos = self._candidate_combinations(parameter_grid)
        if not combos:
            return
        limit = max(1, int(max_evaluations or len(combos)))
        method = str(search_method or "grid").lower()
        if method == "random" and len(combos) > limit:
            rng = random.Random(int(random_seed or 42))
            yield from rng.sample(combos, limit)
            return
        if method in {"bayesian", "adaptive"} and len(combos) > limit:
            yield from self._adaptive_candidates(combos, limit, random_seed)
            return
        yield from combos[:limit]

    def _candidate_combinations(self, parameter_grid: Dict[str, list[Any]]) -> list[Dict[str, Any]]:
        keys = list((parameter_grid or {}).keys())
        if not keys:
            return [{}]
        values = [list(parameter_grid[key]) for key in keys]
        if any(not items for items in values):
            return [{}]
        return [dict(zip(keys, combo)) for combo in product(*values)]

    def _adaptive_candidates(
        self,
        combos: list[Dict[str, Any]],
        limit: int,
        random_seed: int,
    ) -> list[Dict[str, Any]]:
        rng = random.Random(int(random_seed or 42))
        shuffled = list(combos)
        rng.shuffle(shuffled)
        explore_count = max(1, min(len(shuffled), int(limit * 0.35)))
        selected = shuffled[:explore_count]
        seen = {self._candidate_key(item) for item in selected}
        center = self._parameter_center(combos)
        ranked = sorted(combos, key=lambda item: (self._distance_to_center(item, center), self._candidate_key(item)))
        for item in ranked:
            if len(selected) >= limit:
                break
            key = self._candidate_key(item)
            if key in seen:
                continue
            selected.append(item)
            seen.add(key)
        return selected

    def _parameter_center(self, combos: list[Dict[str, Any]]) -> Dict[str, float]:
        center: Dict[str, float] = {}
        keys = set().union(*(item.keys() for item in combos))
        for key in keys:
            numeric = [value for value in (self._numeric_value(item.get(key)) for item in combos) if value is not None]
            if numeric:
                center[key] = sum(numeric) / len(numeric)
        return center

    def _distance_to_center(self, item: Dict[str, Any], center: Dict[str, float]) -> float:
        distance = 0.0
        for key, center_value in center.items():
            value = self._numeric_value(item.get(key))
            if value is None:
                continue
            scale = max(abs(center_value), 1.0)
            distance += ((value - center_value) / scale) ** 2
        return distance

    def _candidate_key(self, item: Dict[str, Any]) -> tuple:
        return tuple((key, item.get(key)) for key in sorted(item.keys()))

    def _numeric_value(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _score(self, metrics: Dict[str, Any], objective: str) -> float:
        value = float(metrics.get(objective, 0.0) or 0.0)
        if objective == "max_drawdown_percent":
            return -value
        return value

    def _normalize_history(self, history, *, period: str = "1h") -> list[Dict[str, Any]]:
        if history is None:
            return []
        if hasattr(history, "to_dict"):
            records = history.to_dict("records")
        else:
            records = list(history)

        rows: list[Dict[str, Any]] = []
        for item in records:
            symbol = normalize_crypto_symbol(item.get("symbol", ""))
            try:
                price = float(item.get("price", item.get("close", 0)) or 0)
            except (TypeError, ValueError):
                price = 0.0
            if not symbol or price <= 0:
                continue
            timestamp = item.get("start_time") or item.get("timestamp") or item.get("time")
            rows.append(
                {
                    "symbol": symbol,
                    "period": str(item.get("period") or period),
                    "price": price,
                    "open": self._float(item.get("open", price), price),
                    "high": self._float(item.get("high", price), price),
                    "low": self._float(item.get("low", price), price),
                    "close": self._float(item.get("close", price), price),
                    "timestamp": timestamp,
                    "start_time": timestamp,
                    "volume": self._float(item.get("volume", 0), 0.0),
                    "amount": self._float(item.get("amount", 0), 0.0),
                    "count": int(item.get("count", 0) or 0),
                }
            )
        rows.sort(key=lambda item: str(item.get("timestamp") or ""))
        return rows

    def _float(self, value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback


StrategyParameterOptimizer = CryptoStrategyParameterOptimizer
