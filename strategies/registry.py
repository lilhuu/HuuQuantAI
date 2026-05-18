"""Strategy templates and factory helpers."""

from __future__ import annotations

import importlib
from typing import Any, Dict

from strategies.bollinger_strategy import BollingerBandsStrategy
from strategies.custom_rule_strategy import CustomRuleStrategy
from strategies.dual_ma_strategy import DualMAStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.rsi_strategy import RSIStrategy


STRATEGY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "dual_ma": {
        "template_id": "dual_ma",
        "name": "Dual Moving Average",
        "description": "Fast/slow moving-average crossover strategy.",
        "parameters": {
            "fast_period": {"type": "int", "default": 5, "min": 1},
            "slow_period": {"type": "int", "default": 20, "min": 2},
            "position_ratio": {"type": "float", "default": 0.1, "min": 0.01, "max": 1},
        },
    },
    "rsi": {
        "template_id": "rsi",
        "name": "RSI",
        "description": "Relative Strength Index oversold/overbought strategy.",
        "parameters": {
            "rsi_period": {"type": "int", "default": 14, "min": 1},
            "oversold": {"type": "float", "default": 30, "min": 0, "max": 100},
            "overbought": {"type": "float", "default": 70, "min": 0, "max": 100},
            "position_ratio": {"type": "float", "default": 0.1, "min": 0.01, "max": 1},
        },
    },
    "custom_rule": {
        "template_id": "custom_rule",
        "name": "Custom Rule",
        "description": "Editable threshold strategy for simple no-code rules.",
        "parameters": {
            "buy_below": {"type": "float", "default": None},
            "sell_above": {"type": "float", "default": None},
            "position_ratio": {"type": "float", "default": 0.1, "min": 0.01, "max": 1},
        },
    },
    "bollinger": {
        "template_id": "bollinger",
        "name": "Bollinger Bands",
        "description": "Mean-reversion strategy using upper and lower Bollinger bands.",
        "parameters": {
            "period": {"type": "int", "default": 20, "min": 2},
            "stddev_multiplier": {"type": "float", "default": 2.0, "min": 0.1},
            "position_ratio": {"type": "float", "default": 0.1, "min": 0.01, "max": 1},
        },
    },
    "momentum": {
        "template_id": "momentum",
        "name": "Momentum",
        "description": "Breakout strategy based on lookback return thresholds.",
        "parameters": {
            "lookback_period": {"type": "int", "default": 10, "min": 1},
            "buy_threshold": {"type": "float", "default": 0.03, "min": 0},
            "sell_threshold": {"type": "float", "default": -0.02, "max": 0},
            "position_ratio": {"type": "float", "default": 0.1, "min": 0.01, "max": 1},
        },
    },
    "python_class": {
        "template_id": "python_class",
        "name": "Python Class",
        "description": "Hot-load a strategy class from an importable Python module.",
        "parameters": {
            "module": {"type": "str", "required": True},
            "class_name": {"type": "str", "required": True},
        },
    },
}


def list_strategy_templates() -> list[Dict[str, Any]]:
    return [dict(template) for template in STRATEGY_TEMPLATES.values()]


def build_strategies_from_config(configured: Dict[str, Any], default_symbols: list[str]) -> Dict[str, Any]:
    configured = configured or {}
    strategies: Dict[str, Any] = {}

    if not configured:
        configured = {"dual_ma": {}}

    for strategy_id, raw_config in configured.items():
        if raw_config is None:
            continue
        strategy_config = dict(raw_config or {})
        if not strategy_config.get("symbols"):
            strategy_config["symbols"] = list(default_symbols)
        strategies[str(strategy_id).strip().lower()] = create_strategy(strategy_id, strategy_config)

    if not strategies:
        strategies["dual_ma"] = create_strategy("dual_ma", {"symbols": list(default_symbols)})
    return strategies


def create_strategy(strategy_id: str, config: Dict[str, Any]):
    strategy_type = str(config.get("type") or _infer_strategy_type(strategy_id)).strip().lower()
    config.setdefault("type", strategy_type)

    if strategy_type in {"dual_ma", "dual_ma_strategy"}:
        return DualMAStrategy(config)
    if strategy_type in {"rsi", "rsi_strategy"}:
        return RSIStrategy(config)
    if strategy_type in {"custom_rule", "threshold"}:
        return CustomRuleStrategy(config)
    if strategy_type in {"bollinger", "bollinger_bands", "bbands"}:
        return BollingerBandsStrategy(config)
    if strategy_type in {"momentum", "breakout"}:
        return MomentumStrategy(config)
    if strategy_type in {"python_class", "custom_python"}:
        return _load_python_strategy(config)

    raise ValueError(f"Unsupported strategy type: {strategy_type}")


def _infer_strategy_type(strategy_id: str) -> str:
    normalized = str(strategy_id or "").strip().lower()
    if normalized.startswith("rsi"):
        return "rsi"
    if normalized.startswith("custom"):
        return "custom_rule"
    if normalized.startswith("bollinger") or normalized.startswith("bb"):
        return "bollinger"
    if normalized.startswith("momentum"):
        return "momentum"
    return "dual_ma"


def _load_python_strategy(config: Dict[str, Any]):
    module_name = str(config.get("module") or "").strip()
    class_name = str(config.get("class_name") or "").strip()
    if not module_name or not class_name:
        raise ValueError("python_class strategies require module and class_name")

    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    module = importlib.reload(module)
    strategy_class = getattr(module, class_name)
    return strategy_class(config)
