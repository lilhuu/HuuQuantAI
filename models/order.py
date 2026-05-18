"""Order model — crypto-compatible with fractional quantities."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL_FILLED = "partial_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """订单模型 — 支持加密货币小数精度"""

    symbol: str
    action: str
    order_type: str
    quantity: float
    price: float
    strategy: str
    order_id: str = None
    status: OrderStatus = OrderStatus.PENDING
    created_time: datetime = None
    filled_time: datetime = None
    filled_price: float = None
    filled_quantity: float = 0.0
    message: str = ""
