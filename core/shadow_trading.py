"""Shadow trading with order-book impact estimation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class FillResult:
    filled_quantity: float
    average_price: float
    total_cost: float
    slippage_pct: float
    levels_consumed: int
    remaining_quantity: float
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_fully_filled(self) -> bool:
        return self.remaining_quantity <= 1e-8


class OrderbookImpactCalculator:
    """Estimate fill price from visible order-book depth."""

    def simulate_fill(
        self,
        order_book: dict[str, Any],
        side: str,
        quantity: float,
        max_slippage_pct: float = 5.0,
    ) -> FillResult:
        side = str(side or "").upper()
        levels = order_book.get("asks" if side == "BUY" else "bids", []) if order_book else []
        quantity = max(float(quantity or 0), 0.0)
        if quantity <= 0 or not levels:
            return FillResult(0.0, 0.0, 0.0, 0.0, 0, quantity, [])

        best_price = float(levels[0][0] or 0)
        remaining = quantity
        filled = 0.0
        total_cost = 0.0
        details: list[dict[str, Any]] = []
        for level_index, level in enumerate(levels, start=1):
            price = float(level[0] or 0)
            amount = float(level[1] or 0)
            if price <= 0 or amount <= 0 or remaining <= 0:
                continue
            take = min(remaining, amount)
            trial_filled = filled + take
            trial_cost = total_cost + take * price
            avg_price = trial_cost / trial_filled if trial_filled else 0.0
            slip = self._slippage(side, best_price, avg_price)
            if slip > max_slippage_pct:
                break
            filled = trial_filled
            total_cost = trial_cost
            remaining -= take
            details.append({"level": level_index, "price": price, "filled": round(take, 8), "cost": round(take * price, 8)})

        average_price = total_cost / filled if filled else 0.0
        return FillResult(
            filled_quantity=round(filled, 8),
            average_price=round(average_price, 8),
            total_cost=round(total_cost, 8),
            slippage_pct=round(self._slippage(side, best_price, average_price), 8),
            levels_consumed=len(details),
            remaining_quantity=round(remaining, 8),
            details=details,
        )

    def _slippage(self, side: str, best_price: float, average_price: float) -> float:
        if best_price <= 0 or average_price <= 0:
            return 0.0
        if side == "BUY":
            return max((average_price - best_price) / best_price * 100, 0.0)
        return max((best_price - average_price) / best_price * 100, 0.0)


@dataclass
class ShadowPosition:
    symbol: str
    quantity: float
    avg_price: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    created_at: str = ""
    signal_source: str = ""
    estimated_slippage_pct: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.avg_price


class ShadowTradingEngine:
    """Track simulated shadow positions without sending real orders."""

    def __init__(
        self,
        market_data_provider: Any,
        impact_calculator: OrderbookImpactCalculator | None = None,
        storage_path: str | None = None,
        max_trade_log: int = 1000,
    ):
        self.provider = market_data_provider
        self.impact = impact_calculator or OrderbookImpactCalculator()
        self.shadow_positions: dict[str, ShadowPosition] = {}
        self.trade_log: list[dict[str, Any]] = []
        self.max_trade_log = max(1, int(max_trade_log or 1000))
        self.storage_path = self._resolve_storage_path(storage_path) if storage_path else None
        if self.storage_path:
            self._setup_storage()
            self._load_state()

    def execute_shadow_trade(
        self,
        symbol: str,
        action: str,
        quantity: float,
        strategy_id: str,
        sl_price: float | None = None,
        tp_price: float | None = None,
    ) -> dict[str, Any]:
        action = str(action or "").upper()
        try:
            order_book = self.provider.fetch_order_book(symbol, limit=20)
        except Exception:
            order_book = None

        if order_book:
            fill = self.impact.simulate_fill(order_book, action, quantity)
        else:
            reference = self._reference_price(symbol)
            slipped = reference * (1.0005 if action == "BUY" else 0.9995)
            fill = FillResult(float(quantity or 0), slipped, float(quantity or 0) * slipped, 0.05, 0, 0.0, [])

        if action == "BUY" and fill.filled_quantity > 0:
            position = ShadowPosition(
                symbol=symbol,
                quantity=fill.filled_quantity,
                avg_price=fill.average_price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                created_at=self._now(),
                signal_source=strategy_id,
                estimated_slippage_pct=fill.slippage_pct,
            )
            self.shadow_positions[symbol] = position
            self._persist_position(position)
        elif action == "SELL":
            self.shadow_positions.pop(symbol, None)
            self._delete_position(symbol)

        record = {
            "timestamp": self._now(),
            "symbol": symbol,
            "action": action,
            "quantity": fill.filled_quantity,
            "price": fill.average_price,
            "slippage_pct": fill.slippage_pct,
            "levels_consumed": fill.levels_consumed,
            "remaining_quantity": fill.remaining_quantity,
            "strategy_id": strategy_id,
            "orderbook_available": bool(order_book),
        }
        self.trade_log.append(record)
        self.trade_log = self.trade_log[-self.max_trade_log :]
        self._persist_trade_log(record, fill.details)
        return record

    def get_positions(self) -> list[dict[str, Any]]:
        return [position.__dict__ | {"notional": position.notional} for position in self.shadow_positions.values()]

    def _reference_price(self, symbol: str) -> float:
        try:
            quotes = self.provider.fetch_quotes([symbol])
            if quotes:
                return float(quotes[0].get("price", 0) or 0)
        except Exception:
            return 0.0
        return 0.0

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _resolve_storage_path(self, storage_path: str) -> str:
        path = Path(str(storage_path))
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def _connect(self) -> sqlite3.Connection:
        if not self.storage_path:
            raise RuntimeError("shadow trading storage is not configured")
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup_storage(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS shadow_positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    avg_price REAL NOT NULL,
                    stop_loss_price REAL,
                    take_profit_price REAL,
                    created_at TEXT NOT NULL,
                    signal_source TEXT DEFAULT '',
                    estimated_slippage_pct REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS shadow_trade_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL DEFAULT 0,
                    price REAL DEFAULT 0,
                    slippage_pct REAL DEFAULT 0,
                    levels_consumed INTEGER DEFAULT 0,
                    remaining_quantity REAL DEFAULT 0,
                    strategy_id TEXT DEFAULT '',
                    orderbook_available INTEGER DEFAULT 0,
                    details_json TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_logs_symbol_time
                    ON shadow_trade_logs(symbol, timestamp DESC);
                """
            )

    def _load_state(self) -> None:
        with self._connect() as conn:
            position_rows = conn.execute(
                """
                SELECT symbol, quantity, avg_price, stop_loss_price, take_profit_price,
                       created_at, signal_source, estimated_slippage_pct
                FROM shadow_positions
                ORDER BY created_at ASC
                """
            ).fetchall()
            log_rows = conn.execute(
                """
                SELECT timestamp, symbol, action, quantity, price, slippage_pct, levels_consumed,
                       remaining_quantity, strategy_id, orderbook_available
                FROM shadow_trade_logs
                ORDER BY log_id DESC
                LIMIT ?
                """,
                (self.max_trade_log,),
            ).fetchall()

        self.shadow_positions = {
            row["symbol"]: ShadowPosition(
                symbol=row["symbol"],
                quantity=float(row["quantity"] or 0),
                avg_price=float(row["avg_price"] or 0),
                stop_loss_price=self._optional_float(row["stop_loss_price"]),
                take_profit_price=self._optional_float(row["take_profit_price"]),
                created_at=str(row["created_at"] or ""),
                signal_source=str(row["signal_source"] or ""),
                estimated_slippage_pct=float(row["estimated_slippage_pct"] or 0),
            )
            for row in position_rows
        }
        self.trade_log = [
            {
                "timestamp": str(row["timestamp"] or ""),
                "symbol": str(row["symbol"] or ""),
                "action": str(row["action"] or ""),
                "quantity": float(row["quantity"] or 0),
                "price": float(row["price"] or 0),
                "slippage_pct": float(row["slippage_pct"] or 0),
                "levels_consumed": int(row["levels_consumed"] or 0),
                "remaining_quantity": float(row["remaining_quantity"] or 0),
                "strategy_id": str(row["strategy_id"] or ""),
                "orderbook_available": bool(row["orderbook_available"]),
            }
            for row in reversed(log_rows)
        ]

    def _persist_position(self, position: ShadowPosition) -> None:
        if not self.storage_path:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO shadow_positions
                    (symbol, quantity, avg_price, stop_loss_price, take_profit_price,
                     created_at, signal_source, estimated_slippage_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.symbol,
                    position.quantity,
                    position.avg_price,
                    position.stop_loss_price,
                    position.take_profit_price,
                    position.created_at,
                    position.signal_source,
                    position.estimated_slippage_pct,
                ),
            )

    def _delete_position(self, symbol: str) -> None:
        if not self.storage_path:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM shadow_positions WHERE symbol = ?", (symbol,))

    def _persist_trade_log(self, record: dict[str, Any], details: list[dict[str, Any]]) -> None:
        if not self.storage_path:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO shadow_trade_logs
                    (timestamp, symbol, action, quantity, price, slippage_pct, levels_consumed,
                     remaining_quantity, strategy_id, orderbook_available, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.get("timestamp", "")),
                    str(record.get("symbol", "")),
                    str(record.get("action", "")),
                    float(record.get("quantity", 0) or 0),
                    float(record.get("price", 0) or 0),
                    float(record.get("slippage_pct", 0) or 0),
                    int(record.get("levels_consumed", 0) or 0),
                    float(record.get("remaining_quantity", 0) or 0),
                    str(record.get("strategy_id", "")),
                    1 if record.get("orderbook_available") else 0,
                    json.dumps(details or [], ensure_ascii=False),
                ),
            )

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)
