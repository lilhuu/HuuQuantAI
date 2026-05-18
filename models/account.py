"""Account model."""

from dataclasses import dataclass


@dataclass
class Account:
    """账户模型"""

    cash: float = 100000.0
    total_assets: float = 100000.0
    market_value: float = 0.0
    available_cash: float = 100000.0
