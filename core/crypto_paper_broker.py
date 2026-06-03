"""Local cryptocurrency paper broker.

This executor intentionally has no live exchange client. It models a USDT cash
account, fractional crypto positions, fees, slippage, partial fills, and logs.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.crypto_market_data_provider import normalize_crypto_symbol
from core.sqlite_utils import configure_sqlite_connection
from core.take_profit_manager import MonitorConfig, TakeProfitManager, TriggerResult


@dataclass
class CryptoPaperOrder:
    symbol: str
    action: str
    quantity: float
    price: float
    strategy: str = "crypto_manual"
    order_type: str = "LIMIT"
    order_id: str = ""
    status: str = "pending"
    message: str = ""
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    realized_pnl: float = 0.0
    created_time: datetime = field(default_factory=datetime.now)
    filled_time: Optional[datetime] = None

    def to_response(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "status": self.status,
            "message": self.message,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "fee": self.fee,
            "realized_pnl": self.realized_pnl,
            "strategy": self.strategy,
            "created_time": self.created_time.isoformat() if self.created_time else None,
            "filled_time": self.filled_time.isoformat() if self.filled_time else None,
        }


class CryptoPaperBrokerExecutor:
    """A deterministic USDT-denominated crypto paper broker."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        defaults = {
            "broker_name": "CryptoPaperBroker",
            "default_quote_currency": "USDT",
            "initial_cash": 10000,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
            "paper_order_enabled": True,
            "real_trading_enabled": False,
            "max_order_notional": 2000,
            "max_position_ratio": 0.5,
            "partial_fill_enabled": True,
            "partial_fill_min_notional": 3000,
            "partial_fill_ratio": 0.6,
            "quantity_precision": 8,
            "price_precision": 8,
            "max_log_entries": 500,
            "max_persisted_log_entries": 5000,
            "persistence_enabled": True,
            "storage_path": "",
        }
        self.config = {**defaults, **(config or {})}
        self.broker_name = str(self.config.get("broker_name", "CryptoPaperBroker"))
        self.quote_currency = str(self.config.get("default_quote_currency", "USDT") or "USDT")
        self.initial_cash = float(self.config.get("initial_cash", 10000) or 10000)
        self.cash = self.initial_cash
        self.fee_rate = float(self.config.get("fee_rate", 0.001) or 0.001)
        self.slippage_rate = float(self.config.get("slippage_rate", 0.0005) or 0.0)
        self.real_trading_enabled = bool(self.config.get("real_trading_enabled", False))
        self.paper_order_enabled = bool(self.config.get("paper_order_enabled", True))
        self.max_order_notional = float(self.config.get("max_order_notional", 2000) or 2000)
        self.max_position_ratio = float(self.config.get("max_position_ratio", 0.5) or 0.5)
        self.partial_fill_enabled = bool(self.config.get("partial_fill_enabled", True))
        self.partial_fill_min_notional = float(self.config.get("partial_fill_min_notional", 3000) or 3000)
        self.partial_fill_ratio = float(self.config.get("partial_fill_ratio", 0.6) or 0.6)
        self.quantity_precision = int(self.config.get("quantity_precision", 8) or 8)
        self.price_precision = int(self.config.get("price_precision", 8) or 8)
        self.storage_path = str(self.config.get("storage_path") or self.config.get("db_path") or "").strip()
        self.persistence_enabled = bool(self.config.get("persistence_enabled", True)) and bool(self.storage_path)
        self._persistence_ready = False
        self.orders: Dict[str, CryptoPaperOrder] = {}
        self.positions: Dict[str, Dict[str, float]] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.paper_logs: List[Dict[str, Any]] = []
        self.is_connected = True
        self.tp_manager: TakeProfitManager | None = None
        if bool(self.config.get("tpsl_monitor_enabled", False)) and self.config.get("market_provider") is not None:
            self.tp_manager = TakeProfitManager(
                self.config["market_provider"],
                MonitorConfig(check_interval_seconds=float(self.config.get("tpsl_check_interval_seconds", 5) or 5)),
            )
            self.tp_manager.set_trigger_callback(self._handle_tpsl_trigger)
            self.tp_manager.start()
        self._setup_persistence()
        restored = self._load_state()
        if restored:
            self._record_log("account_restored", "Crypto paper account restored from local storage")
        else:
            self._record_log("account_initialized", "Crypto paper account initialized")
            self._record_equity_point(reason="account_initialized")
        self._persist_state()

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        strategy: str = "crypto_manual",
        order_type: str = "LIMIT",
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> CryptoPaperOrder:
        order = CryptoPaperOrder(
            symbol=normalize_crypto_symbol(symbol, self.quote_currency),
            action=str(action or "").upper(),
            quantity=self._round_quantity(quantity),
            price=self._round_price(price),
            strategy=str(strategy or "crypto_manual"),
            order_type=str(order_type or "LIMIT").upper(),
            order_id=self._generate_order_id("CPAPER"),
        )
        self.orders[order.order_id] = order

        error = self._validate_order(order)
        if error:
            return self._reject_order(order, error)

        fill_quantity = self._planned_fill_quantity(order)
        if fill_quantity <= 0:
            return self._reject_order(order, "CryptoPaperBroker matching failed")

        self._apply_fill(order, fill_quantity, stop_loss_price=stop_loss_price, take_profit_price=take_profit_price)
        remaining = self._round_quantity(order.quantity - order.filled_quantity)
        if remaining > 0:
            order.status = "partial_filled"
            order.message = f"CryptoPaperBroker partially filled {order.filled_quantity}/{order.quantity}"
            self._record_log("order_partially_filled", order.message, order, {"remaining_quantity": remaining})
        else:
            order.status = "filled"
            order.message = f"CryptoPaperBroker filled {order.filled_quantity}"
            self._record_log("order_filled", order.message, order)
        self._record_equity_point(order=order, reason=order.status)
        self._persist_state()
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(str(order_id))
        if not order or order.status not in {"pending", "partial_filled"}:
            return False
        remaining = self._round_quantity(order.quantity - order.filled_quantity)
        order.status = "cancelled"
        order.message = f"CryptoPaperBroker cancelled remaining {remaining}"
        self._record_log("order_cancelled", order.message, order, {"remaining_quantity": remaining})
        self._record_equity_point(order=order, reason="order_cancelled")
        self._persist_state()
        return True

    def get_account_info(self) -> Dict[str, Any]:
        market_value = self._market_value()
        equity = self.cash + market_value
        return {
            "broker_name": self.broker_name,
            "quote_currency": self.quote_currency,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "available_cash": self.cash,
            "market_value": market_value,
            "equity": equity,
            "total_profit": equity - self.initial_cash,
            "total_return_percent": ((equity - self.initial_cash) / self.initial_cash * 100) if self.initial_cash else 0.0,
            "total_trades": len(self.trade_history),
            "total_fee": sum(float(item.get("fee", 0) or 0) for item in self.trade_history),
            "positions": self.get_positions(),
            "equity_curve": list(self.equity_curve),
            "paper_logs": list(self.paper_logs),
            "real_trading_enabled": self.real_trading_enabled,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for symbol, position in sorted(self.positions.items()):
            quantity = float(position.get("quantity", 0) or 0)
            if quantity <= 0:
                continue
            avg_price = float(position.get("avg_price", 0) or 0)
            current_price = float(position.get("last_price", avg_price) or avg_price)
            market_value = quantity * current_price
            cost_basis = quantity * avg_price
            unrealized_pnl = market_value - cost_basis
            items.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "available": float(position.get("available", quantity) or quantity),
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "market_value": market_value,
                    "cost_basis": cost_basis,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_percent": (unrealized_pnl / cost_basis * 100) if cost_basis else 0.0,
                }
            )
        return items

    def get_orders(self, status: str | None = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        items = list(self.orders.values())
        if normalized_status:
            items = [order for order in items if order.status == normalized_status]
        items.sort(key=lambda order: order.created_time, reverse=True)
        total = len(items)
        safe_offset = max(int(offset or 0), 0)
        safe_limit = max(1, min(int(limit or 100), 500))
        page = items[safe_offset : safe_offset + safe_limit]
        return {
            "items": [order.to_response() for order in page],
            "count": len(page),
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_equity_curve(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.equity_curve[-max(1, min(int(limit or 200), 1000)) :]

    def get_paper_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.paper_logs[-max(1, min(int(limit or 100), 500)) :]

    def _validate_order(self, order: CryptoPaperOrder) -> str:
        if not self.paper_order_enabled:
            return "Crypto paper order switch is disabled"
        if self.real_trading_enabled:
            return "CryptoPaperBroker refuses real_trading_enabled=true"
        if not order.symbol:
            return "symbol is required"
        if order.action not in {"BUY", "SELL"}:
            return "unsupported action"
        if order.quantity <= 0:
            return "quantity must be greater than 0"
        if order.price <= 0:
            return "price must be greater than 0"

        if order.action == "BUY":
            notional = order.quantity * order.price
            if self.max_order_notional > 0 and notional > self.max_order_notional:
                return f"single order notional exceeds {self.max_order_notional} {self.quote_currency}"
            fill_quantity = self._planned_fill_quantity(order)
            estimated_cost = self._fill_notional(order.action, fill_quantity, order.price) * (1 + self.fee_rate)
            if estimated_cost > self.cash:
                return "insufficient USDT cash"
            projected_market_value = self._market_value() + estimated_cost
            max_position_value = self.get_account_info()["equity"] * self.max_position_ratio
            if self.max_position_ratio > 0 and projected_market_value > max_position_value:
                return "crypto max position ratio exceeded"

        if order.action == "SELL":
            current = float(self.positions.get(order.symbol, {}).get("available", 0) or 0)
            if order.quantity > current:
                return "insufficient crypto position; short selling is disabled"
            notional = order.quantity * order.price
            if self.max_order_notional > 0 and notional > self.max_order_notional:
                return f"single order notional exceeds {self.max_order_notional} {self.quote_currency}"
        return ""

    def _planned_fill_quantity(self, order: CryptoPaperOrder) -> float:
        notional = order.quantity * order.price
        if self.partial_fill_enabled and notional >= self.partial_fill_min_notional:
            return self._round_quantity(order.quantity * self.partial_fill_ratio)
        return order.quantity

    def _apply_fill(
        self,
        order: CryptoPaperOrder,
        quantity: float,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> None:
        fill_price = self._slipped_price(order.action, order.price)
        gross = quantity * fill_price
        fee = gross * self.fee_rate
        realized_pnl = 0.0

        if order.action == "BUY":
            self.cash -= gross + fee
            position = self.positions.setdefault(
                order.symbol,
                {"quantity": 0.0, "available": 0.0, "avg_price": 0.0, "last_price": fill_price},
            )
            old_quantity = float(position.get("quantity", 0) or 0)
            total_quantity = old_quantity + quantity
            old_cost = old_quantity * float(position.get("avg_price", 0) or 0)
            position["quantity"] = self._round_quantity(total_quantity)
            position["available"] = self._round_quantity(float(position.get("available", old_quantity) or old_quantity) + quantity)
            position["avg_price"] = (old_cost + gross) / total_quantity if total_quantity else 0.0
            position["last_price"] = fill_price
            position["stop_loss_price"] = float(stop_loss_price or fill_price * 0.98)
            position["take_profit_price"] = float(take_profit_price or fill_price * 1.04)
            if self.tp_manager is not None:
                self.tp_manager.register_position(
                    order.symbol,
                    position["quantity"],
                    position["avg_price"],
                    sl_price=position["stop_loss_price"],
                    tp_price=position["take_profit_price"],
                    position_id=order.order_id,
                )
        else:
            position = self.positions.get(order.symbol, {})
            avg_price = float(position.get("avg_price", 0) or 0)
            realized_pnl = gross - quantity * avg_price - fee
            self.cash += gross - fee
            position["quantity"] = self._round_quantity(float(position.get("quantity", 0) or 0) - quantity)
            position["available"] = self._round_quantity(float(position.get("available", 0) or 0) - quantity)
            position["last_price"] = fill_price
            if float(position.get("quantity", 0) or 0) <= 0:
                self.positions.pop(order.symbol, None)
                if self.tp_manager is not None:
                    self.tp_manager.unregister_position(order.symbol)

        order.filled_price = self._average_fill_price(order, quantity, fill_price)
        order.filled_quantity = self._round_quantity(order.filled_quantity + quantity)
        order.fee += fee
        order.realized_pnl += realized_pnl
        order.filled_time = datetime.now()
        self.trade_history.append(
            {
                "trade_id": f"{order.order_id}-{len(self.trade_history) + 1}",
                "order_id": order.order_id,
                "symbol": order.symbol,
                "action": order.action,
                "quantity": quantity,
                "price": fill_price,
                "fee": fee,
                "realized_pnl": realized_pnl,
                "timestamp": order.filled_time.isoformat(),
                "strategy": order.strategy,
                "cash": self.cash,
            }
        )

    def _handle_tpsl_trigger(self, result: TriggerResult) -> None:
        """Close a paper position after an independent TP/SL trigger."""
        self.place_order(
            symbol=result.symbol,
            action="SELL",
            quantity=result.position_quantity,
            price=result.current_price,
            strategy=f"tpsl_{result.trigger_type.value}",
            order_type="MARKET",
        )

    def _reject_order(self, order: CryptoPaperOrder, message: str) -> CryptoPaperOrder:
        order.status = "rejected"
        order.message = str(message or "order rejected")
        self._record_log("order_rejected", order.message, order, level="WARN")
        self._record_equity_point(order=order, reason="order_rejected")
        self._persist_state()
        return order

    def _fill_notional(self, action: str, quantity: float, price: float) -> float:
        return quantity * self._slipped_price(action, price)

    def _slipped_price(self, action: str, price: float) -> float:
        multiplier = 1 + self.slippage_rate if action == "BUY" else 1 - self.slippage_rate
        return self._round_price(float(price or 0) * multiplier)

    def _average_fill_price(self, order: CryptoPaperOrder, quantity: float, price: float) -> float:
        previous_quantity = float(order.filled_quantity or 0)
        total_quantity = previous_quantity + quantity
        if total_quantity <= 0:
            return price
        previous_value = previous_quantity * float(order.filled_price or 0)
        return self._round_price((previous_value + quantity * price) / total_quantity)

    def _market_value(self) -> float:
        return sum(
            float(position.get("quantity", 0) or 0) * float(position.get("last_price", position.get("avg_price", 0)) or 0)
            for position in self.positions.values()
        )

    def _record_equity_point(self, order: Optional[CryptoPaperOrder] = None, reason: str = "") -> None:
        market_value = self._market_value()
        equity = self.cash + market_value
        self.equity_curve.append(
            {
                "timestamp": datetime.now().isoformat(),
                "cash": round(float(self.cash), 8),
                "market_value": round(float(market_value), 8),
                "equity": round(float(equity), 8),
                "realized_pnl": round(sum(float(item.get("realized_pnl", 0) or 0) for item in self.trade_history), 8),
                "order_id": getattr(order, "order_id", "") or "",
                "reason": reason,
            }
        )
        if len(self.equity_curve) > 1000:
            self.equity_curve = self.equity_curve[-1000:]

    def _record_log(
        self,
        event: str,
        message: str,
        order: Optional[CryptoPaperOrder] = None,
        payload: Optional[Dict[str, Any]] = None,
        level: str = "INFO",
    ) -> None:
        self.paper_logs.append(
            {
                "timestamp": datetime.now().isoformat(),
                "level": level,
                "event": event,
                "order_id": getattr(order, "order_id", "") or "",
                "symbol": getattr(order, "symbol", "") or "",
                "message": message,
                "payload": payload or {},
            }
        )
        max_entries = int(self.config.get("max_log_entries", 500) or 500)
        if len(self.paper_logs) > max_entries:
            self.paper_logs = self.paper_logs[-max_entries:]

    def _generate_order_id(self, prefix: str) -> str:
        return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{uuid4().hex[:8]}"

    def _round_quantity(self, value: Any) -> float:
        return self._round_decimal(value, self.quantity_precision)

    def _round_price(self, value: Any) -> float:
        return self._round_decimal(value, self.price_precision)

    def _round_decimal(self, value: Any, precision: int) -> float:
        try:
            number = Decimal(str(value or 0))
        except (InvalidOperation, ValueError):
            number = Decimal("0")
        quant = Decimal("1").scaleb(-max(0, int(precision or 0)))
        return float(number.quantize(quant, rounding=ROUND_HALF_UP))

    def _setup_persistence(self) -> None:
        if not self.persistence_enabled:
            return
        try:
            path = Path(self.storage_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path = str(path)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS crypto_paper_account (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        broker_name TEXT NOT NULL,
                        quote_currency TEXT NOT NULL,
                        initial_cash TEXT NOT NULL,
                        cash TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS crypto_paper_orders (
                        order_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        action TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        price TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        order_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT,
                        filled_quantity TEXT NOT NULL,
                        filled_price TEXT NOT NULL,
                        fee TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        created_time TEXT,
                        filled_time TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_paper_orders_symbol_created
                        ON crypto_paper_orders(symbol, created_time);
                    CREATE INDEX IF NOT EXISTS idx_crypto_paper_orders_status
                        ON crypto_paper_orders(status);
                    CREATE TABLE IF NOT EXISTS crypto_paper_positions (
                        symbol TEXT PRIMARY KEY,
                        quantity TEXT NOT NULL,
                        available TEXT NOT NULL,
                        avg_price TEXT NOT NULL,
                        last_price TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS crypto_paper_trades (
                        trade_id TEXT PRIMARY KEY,
                        order_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        action TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        price TEXT NOT NULL,
                        fee TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        cash TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_paper_trades_symbol_time
                        ON crypto_paper_trades(symbol, timestamp);
                    CREATE TABLE IF NOT EXISTS crypto_paper_equity_curve (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        cash TEXT NOT NULL,
                        market_value TEXT NOT NULL,
                        equity TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        order_id TEXT,
                        reason TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_paper_equity_time
                        ON crypto_paper_equity_curve(timestamp);
                    CREATE TABLE IF NOT EXISTS crypto_paper_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        event TEXT NOT NULL,
                        order_id TEXT,
                        symbol TEXT,
                        message TEXT,
                        payload TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_paper_logs_event_time
                        ON crypto_paper_logs(event, timestamp);
                    """
                )
            self._persistence_ready = True
        except Exception as exc:
            self.persistence_enabled = False
            self._persistence_ready = False
            self.paper_logs.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "level": "WARN",
                    "event": "persistence_disabled",
                    "order_id": "",
                    "symbol": "",
                    "message": f"Crypto paper persistence disabled: {exc}",
                    "payload": {},
                }
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.storage_path, timeout=30)
        configure_sqlite_connection(conn)
        conn.row_factory = sqlite3.Row
        return conn

    def _existing_equity_keys(self, conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
        rows = conn.execute("SELECT timestamp, COALESCE(order_id, '') AS order_id, COALESCE(reason, '') AS reason FROM crypto_paper_equity_curve").fetchall()
        return {(str(row["timestamp"]), str(row["order_id"]), str(row["reason"])) for row in rows}

    def _existing_log_keys(self, conn: sqlite3.Connection) -> set[tuple[str, str, str, str, str]]:
        rows = conn.execute(
            """
            SELECT timestamp, event, COALESCE(order_id, '') AS order_id,
                   COALESCE(symbol, '') AS symbol, COALESCE(message, '') AS message
            FROM crypto_paper_logs
            """
        ).fetchall()
        return {
            (
                str(row["timestamp"]),
                str(row["event"]),
                str(row["order_id"]),
                str(row["symbol"]),
                str(row["message"]),
            )
            for row in rows
        }

    def _load_state(self) -> bool:
        if not self.persistence_enabled or not self._persistence_ready:
            return False
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM crypto_paper_account WHERE id = 1").fetchone()
            if not account:
                return False

            self.broker_name = str(account["broker_name"] or self.broker_name)
            self.quote_currency = str(account["quote_currency"] or self.quote_currency)
            self.initial_cash = self._to_float(account["initial_cash"], self.initial_cash)
            self.cash = self._to_float(account["cash"], self.cash)

            self.orders = {}
            for row in conn.execute("SELECT * FROM crypto_paper_orders ORDER BY created_time"):
                order = CryptoPaperOrder(
                    symbol=str(row["symbol"] or ""),
                    action=str(row["action"] or "").upper(),
                    quantity=self._to_float(row["quantity"]),
                    price=self._to_float(row["price"]),
                    strategy=str(row["strategy"] or "crypto_manual"),
                    order_type=str(row["order_type"] or "LIMIT").upper(),
                    order_id=str(row["order_id"] or ""),
                    status=str(row["status"] or "pending"),
                    message=str(row["message"] or ""),
                    filled_quantity=self._to_float(row["filled_quantity"]),
                    filled_price=self._to_float(row["filled_price"]),
                    fee=self._to_float(row["fee"]),
                    realized_pnl=self._to_float(row["realized_pnl"]),
                    created_time=self._parse_datetime(row["created_time"]) or datetime.now(),
                    filled_time=self._parse_datetime(row["filled_time"]),
                )
                if order.order_id:
                    self.orders[order.order_id] = order

            self.positions = {
                str(row["symbol"]): {
                    "quantity": self._to_float(row["quantity"]),
                    "available": self._to_float(row["available"]),
                    "avg_price": self._to_float(row["avg_price"]),
                    "last_price": self._to_float(row["last_price"]),
                }
                for row in conn.execute("SELECT * FROM crypto_paper_positions ORDER BY symbol")
            }

            self.trade_history = [
                {
                    "trade_id": str(row["trade_id"] or ""),
                    "order_id": str(row["order_id"] or ""),
                    "symbol": str(row["symbol"] or ""),
                    "action": str(row["action"] or ""),
                    "quantity": self._to_float(row["quantity"]),
                    "price": self._to_float(row["price"]),
                    "fee": self._to_float(row["fee"]),
                    "realized_pnl": self._to_float(row["realized_pnl"]),
                    "timestamp": str(row["timestamp"] or ""),
                    "strategy": str(row["strategy"] or "crypto_manual"),
                    "cash": self._to_float(row["cash"]),
                }
                for row in conn.execute("SELECT * FROM crypto_paper_trades ORDER BY timestamp, trade_id")
            ]

            self.equity_curve = [
                {
                    "timestamp": str(row["timestamp"] or ""),
                    "cash": self._to_float(row["cash"]),
                    "market_value": self._to_float(row["market_value"]),
                    "equity": self._to_float(row["equity"]),
                    "realized_pnl": self._to_float(row["realized_pnl"]),
                    "order_id": str(row["order_id"] or ""),
                    "reason": str(row["reason"] or ""),
                }
                for row in conn.execute("SELECT * FROM crypto_paper_equity_curve ORDER BY id")
            ]

            self.paper_logs = []
            for row in conn.execute("SELECT * FROM crypto_paper_logs ORDER BY id"):
                try:
                    payload = json.loads(row["payload"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                self.paper_logs.append(
                    {
                        "timestamp": str(row["timestamp"] or ""),
                        "level": str(row["level"] or "INFO"),
                        "event": str(row["event"] or ""),
                        "order_id": str(row["order_id"] or ""),
                        "symbol": str(row["symbol"] or ""),
                        "message": str(row["message"] or ""),
                        "payload": payload,
                    }
                )
        return True

    def _persist_state(self) -> None:
        if not self.persistence_enabled or not self._persistence_ready:
            return
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO crypto_paper_account
                    (id, broker_name, quote_currency, initial_cash, cash, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    broker_name = excluded.broker_name,
                    quote_currency = excluded.quote_currency,
                    initial_cash = excluded.initial_cash,
                    cash = excluded.cash,
                    updated_at = excluded.updated_at
                """,
                (self.broker_name, self.quote_currency, self._text(self.initial_cash), self._text(self.cash), now),
            )

            conn.executemany(
                """
                INSERT INTO crypto_paper_orders
                    (order_id, symbol, action, quantity, price, strategy, order_type, status, message,
                     filled_quantity, filled_price, fee, realized_pnl, created_time, filled_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    action = excluded.action,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    strategy = excluded.strategy,
                    order_type = excluded.order_type,
                    status = excluded.status,
                    message = excluded.message,
                    filled_quantity = excluded.filled_quantity,
                    filled_price = excluded.filled_price,
                    fee = excluded.fee,
                    realized_pnl = excluded.realized_pnl,
                    created_time = excluded.created_time,
                    filled_time = excluded.filled_time
                """,
                [
                    (
                        order.order_id,
                        order.symbol,
                        order.action,
                        self._text(order.quantity),
                        self._text(order.price),
                        order.strategy,
                        order.order_type,
                        order.status,
                        order.message,
                        self._text(order.filled_quantity),
                        self._text(order.filled_price),
                        self._text(order.fee),
                        self._text(order.realized_pnl),
                        order.created_time.isoformat() if order.created_time else "",
                        order.filled_time.isoformat() if order.filled_time else "",
                    )
                    for order in self.orders.values()
                ],
            )

            active_position_symbols = [
                symbol
                for symbol, position in self.positions.items()
                if float(position.get("quantity", 0) or 0) > 0
            ]
            if active_position_symbols:
                placeholders = ",".join("?" for _ in active_position_symbols)
                conn.execute(f"DELETE FROM crypto_paper_positions WHERE symbol NOT IN ({placeholders})", active_position_symbols)
            else:
                conn.execute("DELETE FROM crypto_paper_positions")
            conn.executemany(
                """
                INSERT INTO crypto_paper_positions
                    (symbol, quantity, available, avg_price, last_price, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    available = excluded.available,
                    avg_price = excluded.avg_price,
                    last_price = excluded.last_price,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        symbol,
                        self._text(position.get("quantity", 0)),
                        self._text(position.get("available", 0)),
                        self._text(position.get("avg_price", 0)),
                        self._text(position.get("last_price", 0)),
                        now,
                    )
                    for symbol, position in self.positions.items()
                    if float(position.get("quantity", 0) or 0) > 0
                ],
            )

            conn.executemany(
                """
                INSERT INTO crypto_paper_trades
                    (trade_id, order_id, symbol, action, quantity, price, fee, realized_pnl, timestamp, strategy, cash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    order_id = excluded.order_id,
                    symbol = excluded.symbol,
                    action = excluded.action,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    fee = excluded.fee,
                    realized_pnl = excluded.realized_pnl,
                    timestamp = excluded.timestamp,
                    strategy = excluded.strategy,
                    cash = excluded.cash
                """,
                [
                    (
                        str(item.get("trade_id", "")),
                        str(item.get("order_id", "")),
                        str(item.get("symbol", "")),
                        str(item.get("action", "")),
                        self._text(item.get("quantity", 0)),
                        self._text(item.get("price", 0)),
                        self._text(item.get("fee", 0)),
                        self._text(item.get("realized_pnl", 0)),
                        str(item.get("timestamp", "")),
                        str(item.get("strategy", "crypto_manual")),
                        self._text(item.get("cash", 0)),
                    )
                    for item in self.trade_history
                ],
            )

            existing_equity_keys = self._existing_equity_keys(conn)
            new_equity_items = []
            for item in self.equity_curve:
                key = (str(item.get("timestamp", "")), str(item.get("order_id", "")), str(item.get("reason", "")))
                if key in existing_equity_keys:
                    continue
                existing_equity_keys.add(key)
                new_equity_items.append(item)
            conn.executemany(
                """
                INSERT INTO crypto_paper_equity_curve
                    (timestamp, cash, market_value, equity, realized_pnl, order_id, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(item.get("timestamp", "")),
                        self._text(item.get("cash", 0)),
                        self._text(item.get("market_value", 0)),
                        self._text(item.get("equity", 0)),
                        self._text(item.get("realized_pnl", 0)),
                        str(item.get("order_id", "")),
                        str(item.get("reason", "")),
                    )
                    for item in new_equity_items
                ],
            )

            existing_log_keys = self._existing_log_keys(conn)
            new_log_items = []
            for item in self.paper_logs:
                key = (
                    str(item.get("timestamp", "")),
                    str(item.get("event", "")),
                    str(item.get("order_id", "")),
                    str(item.get("symbol", "")),
                    str(item.get("message", "")),
                )
                if key in existing_log_keys:
                    continue
                existing_log_keys.add(key)
                new_log_items.append(item)
            conn.executemany(
                """
                INSERT INTO crypto_paper_logs
                    (timestamp, level, event, order_id, symbol, message, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(item.get("timestamp", "")),
                        str(item.get("level", "INFO")),
                        str(item.get("event", "")),
                        str(item.get("order_id", "")),
                        str(item.get("symbol", "")),
                        str(item.get("message", "")),
                        json.dumps(item.get("payload", {}) or {}, ensure_ascii=False),
                    )
                    for item in new_log_items
                ],
            )
            self._prune_persisted_logs(conn)

    def _prune_persisted_logs(self, conn: sqlite3.Connection) -> None:
        max_entries = max(0, int(self.config.get("max_persisted_log_entries", 5000) or 0))
        if max_entries <= 0:
            return
        conn.execute(
            """
            DELETE FROM crypto_paper_logs
            WHERE id NOT IN (
                SELECT id FROM crypto_paper_logs
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (max_entries,),
        )

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _to_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _text(self, value: Any) -> str:
        return format(self._to_float(value), ".12g")
