"""SQLite cache for crypto market snapshots and candles."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List

from core.crypto_market_data_provider import normalize_crypto_symbol


class CryptoMarketCache:
    """Persist the latest ticker snapshots and OHLCV candles."""

    def __init__(self, storage_path: str | None = None) -> None:
        self.storage_path = str(storage_path or "").strip()
        self.enabled = bool(self.storage_path)
        self._ready = False
        self._lock = threading.RLock()
        self._setup()

    def upsert_quotes(self, rows: Iterable[dict[str, Any]]) -> None:
        if not self._ready:
            return
        now = datetime.now().isoformat()
        payload = []
        for row in rows:
            symbol = normalize_crypto_symbol(row.get("symbol"))
            if not symbol:
                continue
            payload.append(
                (
                    symbol,
                    self._float(row.get("price")),
                    self._float(row.get("open")),
                    self._float(row.get("high")),
                    self._float(row.get("low")),
                    self._float(row.get("volume")),
                    self._float(row.get("amount")),
                    self._float(row.get("change")),
                    self._float(row.get("change_amount")),
                    self._float(row.get("bid")),
                    self._float(row.get("ask")),
                    str(row.get("timestamp") or now),
                    str(row.get("source") or "binance"),
                    now,
                )
            )
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO crypto_quotes_snapshot
                    (symbol, price, open, high, low, volume, amount, change, change_amount, bid, ask, timestamp, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    price = excluded.price,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    change = excluded.change,
                    change_amount = excluded.change_amount,
                    bid = excluded.bid,
                    ask = excluded.ask,
                    timestamp = excluded.timestamp,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def get_quotes(self, symbols: Iterable[str]) -> List[dict[str, Any]]:
        if not self._ready:
            return []
        normalized = [normalize_crypto_symbol(symbol) for symbol in symbols]
        normalized = [symbol for symbol in normalized if symbol]
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, price, open, high, low, volume, amount, change, change_amount, bid, ask, timestamp
                FROM crypto_quotes_snapshot
                WHERE symbol IN ({placeholders})
                ORDER BY symbol
                """,
                normalized,
            ).fetchall()
        return [
            {
                "symbol": str(row["symbol"]),
                "price": self._float(row["price"]),
                "open": self._float(row["open"]),
                "high": self._float(row["high"]),
                "low": self._float(row["low"]),
                "volume": self._float(row["volume"]),
                "amount": self._float(row["amount"]),
                "change": self._float(row["change"]),
                "change_amount": self._float(row["change_amount"]),
                "bid": self._float(row["bid"]),
                "ask": self._float(row["ask"]),
                "timestamp": str(row["timestamp"] or ""),
                "source": "cache_binance",
            }
            for row in rows
        ]

    def upsert_exchange_info(self, rows: list[dict[str, Any]]) -> None:
        if not self._ready or not rows:
            return
        now = datetime.now().isoformat()
        payload = []
        for row in rows:
            symbol = normalize_crypto_symbol(row.get("symbol"))
            if not symbol:
                continue
            payload.append(
                (
                    symbol,
                    str(row.get("base") or "").upper(),
                    str(row.get("quote") or "").upper(),
                    str(row.get("status") or "active"),
                    int(row.get("price_precision") or 0),
                    int(row.get("quantity_precision") or 0),
                    self._float(row.get("min_notional")),
                    now,
                )
            )
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO crypto_exchange_info
                    (symbol, base, quote, status, price_precision, quantity_precision, min_notional, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    base = excluded.base,
                    quote = excluded.quote,
                    status = excluded.status,
                    price_precision = excluded.price_precision,
                    quantity_precision = excluded.quantity_precision,
                    min_notional = excluded.min_notional,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def get_symbols(
        self,
        quote: str | None = None,
        search: str | None = None,
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated symbol list with optional quote and search filters."""
        if not self._ready:
            return [], 0
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(int(offset or 0), 0)
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(str(status))
        if quote:
            conditions.append("quote = ?")
            params.append(str(quote).upper())
        if search:
            conditions.append("(symbol LIKE ? OR base LIKE ?)")
            pattern = f"%{str(search).upper()}%"
            params.extend([pattern, pattern])
        where = " AND ".join(conditions) if conditions else "1=1"
        with self._lock, self._connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM crypto_exchange_info WHERE {where}",
                params,
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                f"""
                SELECT symbol, base, quote, status, price_precision, quantity_precision, min_notional
                FROM crypto_exchange_info
                WHERE {where}
                ORDER BY symbol
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
        items = [
            {
                "symbol": str(row["symbol"]),
                "base": str(row["base"]),
                "quote": str(row["quote"]),
                "status": str(row["status"]),
                "price_precision": int(row["price_precision"] or 0),
                "quantity_precision": int(row["quantity_precision"] or 0),
                "min_notional": self._float(row["min_notional"]),
            }
            for row in rows
        ]
        return items, total

    def upsert_klines(self, rows: Iterable[dict[str, Any]]) -> None:
        if not self._ready:
            return
        now = datetime.now().isoformat()
        payload = []
        for row in rows:
            symbol = normalize_crypto_symbol(row.get("symbol"))
            period = str(row.get("period") or "").strip()
            start_time = str(row.get("start_time") or "").strip()
            if not symbol or not period or not start_time:
                continue
            payload.append(
                (
                    symbol,
                    period,
                    start_time,
                    str(row.get("end_time") or start_time),
                    self._float(row.get("open")),
                    self._float(row.get("high")),
                    self._float(row.get("low")),
                    self._float(row.get("close")),
                    self._float(row.get("volume")),
                    self._float(row.get("amount")),
                    int(row.get("count") or 0),
                    str(row.get("source") or "binance"),
                    now,
                )
            )
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO crypto_klines
                    (symbol, period, start_time, end_time, open, high, low, close, volume, amount, count, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, period, start_time) DO UPDATE SET
                    end_time = excluded.end_time,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    count = excluded.count,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def get_klines(self, symbol: str, period: str, limit: int = 200) -> List[dict[str, Any]]:
        if not self._ready:
            return []
        normalized_symbol = normalize_crypto_symbol(symbol)
        safe_limit = max(1, min(int(limit or 200), 1000))
        if not normalized_symbol:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, period, start_time, end_time, open, high, low, close, volume, amount, count
                FROM crypto_klines
                WHERE symbol = ? AND period = ?
                ORDER BY start_time DESC
                LIMIT ?
                """,
                (normalized_symbol, str(period or "1h"), safe_limit),
            ).fetchall()
        items = [
            {
                "symbol": str(row["symbol"]),
                "period": str(row["period"]),
                "start_time": str(row["start_time"]),
                "end_time": str(row["end_time"]),
                "open": self._float(row["open"]),
                "high": self._float(row["high"]),
                "low": self._float(row["low"]),
                "close": self._float(row["close"]),
                "volume": self._float(row["volume"]),
                "amount": self._float(row["amount"]),
                "count": int(row["count"] or 0),
            }
            for row in rows
        ]
        items.reverse()
        return items

    def _setup(self) -> None:
        if not self.enabled:
            return
        try:
            path = Path(self.storage_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path = str(path)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS crypto_quotes_snapshot (
                        symbol TEXT PRIMARY KEY,
                        price REAL NOT NULL DEFAULT 0,
                        open REAL NOT NULL DEFAULT 0,
                        high REAL NOT NULL DEFAULT 0,
                        low REAL NOT NULL DEFAULT 0,
                        volume REAL NOT NULL DEFAULT 0,
                        amount REAL NOT NULL DEFAULT 0,
                        change REAL NOT NULL DEFAULT 0,
                        change_amount REAL NOT NULL DEFAULT 0,
                        bid REAL NOT NULL DEFAULT 0,
                        ask REAL NOT NULL DEFAULT 0,
                        timestamp TEXT,
                        source TEXT NOT NULL DEFAULT 'binance',
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS crypto_klines (
                        symbol TEXT NOT NULL,
                        period TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL DEFAULT 0,
                        amount REAL NOT NULL DEFAULT 0,
                        count INTEGER NOT NULL DEFAULT 0,
                        source TEXT NOT NULL DEFAULT 'binance',
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (symbol, period, start_time)
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_klines_symbol_period_time
                        ON crypto_klines(symbol, period, start_time);
                    CREATE TABLE IF NOT EXISTS crypto_exchange_info (
                        symbol TEXT PRIMARY KEY,
                        base TEXT NOT NULL,
                        quote TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        price_precision INTEGER DEFAULT 0,
                        quantity_precision INTEGER DEFAULT 0,
                        min_notional REAL DEFAULT 0.0,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_crypto_exchange_info_quote
                        ON crypto_exchange_info(quote);
                    CREATE INDEX IF NOT EXISTS idx_crypto_exchange_info_base
                        ON crypto_exchange_info(base);
                    """
                )
            self._ready = True
        except Exception:
            self.enabled = False
            self._ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
