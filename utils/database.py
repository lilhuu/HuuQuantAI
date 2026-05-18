"""Database placeholder (SQLite)."""

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: str = "data/trader.db") -> None:
        Path("data").mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def save_trade(self, symbol: str, side: str, price: float, quantity: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO trades(symbol, side, price, quantity) VALUES(?,?,?,?)",
            (symbol, side, price, quantity),
        )
        self.conn.commit()
