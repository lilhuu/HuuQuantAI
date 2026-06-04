"""Advisory-only AI chat assistant for the crypto workspace."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.ai_signal_advisor import AiAdvisorConfig, safe_json, utc_now
from core.sqlite_utils import configure_sqlite_connection


CHAT_SYSTEM_PROMPT = (
    "You are HuuQuantAI's advisory-only crypto quant assistant. "
    "Answer in Chinese unless the user asks otherwise. Use the supplied market, K-line, account, "
    "position, order, and risk context when relevant. Do not promise profits. Do not recommend "
    "leverage, short selling, mainnet trading, or bypassing risk checks. You cannot place orders, "
    "cannot call paper/testnet/mainnet trading endpoints, and cannot change trading configuration. "
    "If the user asks you to trade, explain the risk and tell them to use the manual simulated "
    "trading controls themselves. Keep answers concise, practical, and clearly marked as research "
    "or simulated-trading advice."
)


class AiChatAssistant:
    """OpenAI-backed natural-language assistant.

    The class only returns text. It does not expose tools and cannot execute
    paper, testnet, or real orders.
    """

    def __init__(self, config: dict[str, Any] | AiAdvisorConfig | None = None) -> None:
        self.config = config if isinstance(config, AiAdvisorConfig) else AiAdvisorConfig.from_dict(config)

    def chat(
        self,
        *,
        message: str,
        context_summary: dict[str, Any],
        recent_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("AI assistant is disabled in config")
        if self.config.provider != "openai":
            raise RuntimeError(f"unsupported AI provider: {self.config.provider}")
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"missing OpenAI API key env: {self.config.api_key_env}")

        payload = {
            "user_message": str(message or "").strip(),
            "context_summary": context_summary,
            "recent_messages": [
                {
                    "role": str(item.get("role") or ""),
                    "content": str(item.get("content") or "")[:2000],
                    "created_at": str(item.get("created_at") or ""),
                }
                for item in (recent_messages or [])[-12:]
            ],
            "safety": {
                "advisory_only": True,
                "real_trading_allowed": False,
                "paper_order_allowed_by_ai": False,
                "testnet_order_allowed_by_ai": False,
                "manual_confirm_required": True,
            },
        }

        last_error: Exception | None = None
        for model in [self.config.model, self.config.fallback_model]:
            if not model:
                continue
            try:
                content = self._call_openai(api_key=api_key, model=model, payload=payload)
                if not content.strip():
                    raise ValueError("OpenAI chat response was empty")
                return {"model": model, "content": content.strip()}
            except Exception as exc:  # pragma: no cover - covered by service tests with monkeypatches.
                last_error = exc
                if model == self.config.fallback_model:
                    break
        raise RuntimeError(f"OpenAI AI chat request failed: {last_error}")

    def _call_openai(self, *, api_key: str, model: str, payload: dict[str, Any]) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=CHAT_SYSTEM_PROMPT,
            input=safe_json(payload),
        )
        return getattr(response, "output_text", "") or self._extract_output_text(response)

    def _extract_output_text(self, response: Any) -> str:
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()


class AiChatStore:
    """SQLite-backed chat session and message store."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._setup()

    def save_exchange(
        self,
        *,
        session_id: str | None,
        title_seed: str,
        user_content: str,
        assistant_content: str,
        model: str,
        context_summary: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            session = self._get_session(conn, session_id) if session_id else None
            if session_id and session is None:
                return {}
            if session is None:
                session_id = self._new_session_id()
                title = self._make_title(title_seed)
                conn.execute(
                    """
                    INSERT INTO ai_chat_sessions(session_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, title, now, now),
                )
            user_message = self._insert_message(
                conn,
                session_id=str(session_id),
                role="user",
                content=user_content,
                model="",
                context_summary={},
                created_at=now,
            )
            assistant_message = self._insert_message(
                conn,
                session_id=str(session_id),
                role="assistant",
                content=assistant_content,
                model=model,
                context_summary=context_summary,
                created_at=utc_now(),
            )
            conn.execute(
                """
                UPDATE ai_chat_sessions
                SET updated_at = ?
                WHERE session_id = ?
                """,
                (assistant_message["created_at"], session_id),
            )
            session = self._get_session(conn, str(session_id))
        return {
            "session": session,
            "user_message": user_message,
            "assistant_message": assistant_message,
        }

    def list_sessions(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit or 50), 200))
        safe_offset = max(0, int(offset or 0))
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM ai_chat_sessions").fetchone()[0]
            rows = conn.execute(
                """
                SELECT s.*,
                       COUNT(m.message_id) AS message_count,
                       (
                         SELECT content
                         FROM ai_chat_messages last_m
                         WHERE last_m.session_id = s.session_id
                         ORDER BY last_m.created_at DESC, last_m.message_id DESC
                         LIMIT 1
                       ) AS last_message
                FROM ai_chat_sessions s
                LEFT JOIN ai_chat_messages m ON m.session_id = s.session_id
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
            ).fetchall()
        return {
            "items": [self._session_row_to_record(row) for row in rows],
            "count": len(rows),
            "total": int(total or 0),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_session_detail(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            session = self._get_session(conn, session_id)
            if not session:
                return None
            rows = conn.execute(
                """
                SELECT *
                FROM ai_chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, message_id ASC
                """,
                (str(session_id),),
            ).fetchall()
        return {"session": session, "messages": [self._message_row_to_record(row) for row in rows]}

    def list_messages(self, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 12), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, message_id DESC
                LIMIT ?
                """,
                (str(session_id), safe_limit),
            ).fetchall()
        return list(reversed([self._message_row_to_record(row) for row in rows]))

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM ai_chat_sessions WHERE session_id = ?", (str(session_id),))
        return cursor.rowcount > 0

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    context_summary_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES ai_chat_sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_updated
                    ON ai_chat_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_created
                    ON ai_chat_messages(session_id, created_at ASC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        configure_sqlite_connection(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _get_session(self, conn: sqlite3.Connection, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        row = conn.execute(
            """
            SELECT s.*,
                   COUNT(m.message_id) AS message_count,
                   (
                     SELECT content
                     FROM ai_chat_messages last_m
                     WHERE last_m.session_id = s.session_id
                     ORDER BY last_m.created_at DESC, last_m.message_id DESC
                     LIMIT 1
                   ) AS last_message
            FROM ai_chat_sessions s
            LEFT JOIN ai_chat_messages m ON m.session_id = s.session_id
            WHERE s.session_id = ?
            GROUP BY s.session_id
            """,
            (str(session_id),),
        ).fetchone()
        return self._session_row_to_record(row) if row else None

    def _insert_message(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        role: str,
        content: str,
        model: str,
        context_summary: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        message_id = self._new_message_id(role)
        record = {
            "message_id": message_id,
            "session_id": session_id,
            "role": role,
            "content": str(content or ""),
            "model": str(model or ""),
            "context_summary": context_summary,
            "created_at": created_at,
        }
        conn.execute(
            """
            INSERT INTO ai_chat_messages
                (message_id, session_id, role, content, model, context_summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["message_id"],
                record["session_id"],
                record["role"],
                record["content"],
                record["model"],
                safe_json(record["context_summary"]),
                record["created_at"],
            ),
        )
        return record

    def _session_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"] or 0) if "message_count" in row.keys() else 0,
            "last_message": str(row["last_message"] or "") if "last_message" in row.keys() else "",
        }

    def _message_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"] or "",
            "context_summary": json.loads(row["context_summary_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def _new_session_id(self) -> str:
        return f"AICHAT_{int(time.time() * 1000)}_{uuid4().hex[:8]}"

    def _new_message_id(self, role: str) -> str:
        return f"AICHATMSG_{role.upper()}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"

    def _make_title(self, seed: str) -> str:
        normalized = " ".join(str(seed or "AI 对话").strip().split())
        return normalized[:36] or "AI 对话"
