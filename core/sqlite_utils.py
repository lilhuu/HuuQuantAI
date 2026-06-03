"""Shared SQLite connection tuning for local runtime stores."""

from __future__ import annotations

import sqlite3


def configure_sqlite_connection(conn: sqlite3.Connection, *, wal: bool = True) -> sqlite3.Connection:
    """Apply concurrency-friendly pragmas to a SQLite connection."""
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn
