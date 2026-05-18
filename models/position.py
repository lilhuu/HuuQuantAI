"""Position model — crypto-compatible with fractional quantities."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Position:
    """持仓模型 — 支持加密货币小数精度"""

    symbol: str
    quantity: float
    avg_price: float
    current_price: float
    market_value: float
    pnl: float
    pnl_percent: float
    update_time: datetime
