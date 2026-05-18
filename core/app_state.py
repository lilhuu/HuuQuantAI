"""Local application state storage for auth and user preferences."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional


class AppStateStore:
    """Persist users, sessions, and user preferences in a local SQLite file."""

    def __init__(self, db_path: str = "data/app_state.db") -> None:
        self.db_path = db_path
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_database(self) -> None:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    display_name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    last_used_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY,
                    preferences_json TEXT NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                ON sessions (user_id)
                """
            )
            conn.commit()

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        return int(row[0]) if row else 0

    def create_user(
        self,
        username: str,
        password_hash: str,
        password_salt: str,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        timestamp = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, password_salt, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, password_hash, password_salt, display_name, timestamp, timestamp),
            )
            conn.commit()
            user_id = int(cursor.lastrowid)
        return self.get_user_by_id(user_id) or {}

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? LIMIT 1",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ? LIMIT 1",
                (int(user_id),),
            ).fetchone()
        return dict(row) if row else None

    def save_session(self, token_hash: str, user_id: int, expires_at: str) -> Dict[str, Any]:
        timestamp = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_hash, int(user_id), timestamp, expires_at, timestamp),
            )
            conn.commit()
        return self.get_session(token_hash) or {}

    def get_session(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    sessions.token_hash,
                    sessions.user_id,
                    sessions.created_at,
                    sessions.expires_at,
                    sessions.last_used_at,
                    users.username,
                    users.display_name,
                    users.is_active,
                    users.created_at AS user_created_at
                FROM sessions
                JOIN users ON users.user_id = sessions.user_id
                WHERE sessions.token_hash = ?
                LIMIT 1
                """,
                (token_hash,),
            ).fetchone()
        return dict(row) if row else None

    def touch_session(self, token_hash: str) -> None:
        timestamp = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_used_at = ? WHERE token_hash = ?",
                (timestamp, token_hash),
            )
            conn.commit()

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            conn.commit()

    def save_user_preferences(self, user_id: int, preferences: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = datetime.now().isoformat()
        payload = json.dumps(preferences or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences (user_id, preferences_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferences_json = excluded.preferences_json,
                    updated_at = excluded.updated_at
                """,
                (int(user_id), payload, timestamp),
            )
            conn.commit()
        return self.get_user_preferences(user_id)

    def get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT preferences_json, updated_at FROM user_preferences WHERE user_id = ? LIMIT 1",
                (int(user_id),),
            ).fetchone()

        if not row:
            return {"preferences": {}, "updated_at": None}

        try:
            preferences = json.loads(row["preferences_json"] or "{}")
        except json.JSONDecodeError:
            preferences = {}
        return {"preferences": preferences, "updated_at": row["updated_at"]}
