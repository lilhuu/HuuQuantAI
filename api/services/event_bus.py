"""Durable local event bus for realtime order and system updates."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Dict, Optional

from core.desktop_paths import resolve_writable_path


EventCallback = Callable[[Dict[str, Any]], None]
logger = logging.getLogger(__name__)


def _default_event_bus_db_path() -> Path:
    explicit = os.getenv("AUTO_TRADER_EVENT_BUS_DB", "").strip()
    if explicit:
        path = Path(explicit)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return resolve_writable_path("data/event_bus.db", default_relative="data/event_bus.db")


class EventBus:
    """Thread-safe pub/sub event bus with optional SQLite-backed event log.

    WebSocket subscribers are process-local by nature, but the event log is durable.
    After an API restart the frontend can reconnect and replay events by last_event_id.
    """

    EVENT_COLUMNS = [
        "topic",
        "event_type",
        "status",
        "message",
        "timestamp",
        "cached_at",
        "payload_json",
    ]

    def __init__(
        self,
        recent_events_per_topic: int = 100,
        persistent_db_path: str | os.PathLike[str] | None = None,
        max_persisted_events: int = 10000,
    ) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, dict[int, EventCallback]] = {}
        self._topic_stats: dict[str, dict[str, Any]] = {}
        self._recent_events: dict[str, deque[dict[str, Any]]] = {}
        self._next_id = 0
        self._next_event_id = 0
        self._recent_events_per_topic = max(int(recent_events_per_topic or 0), 1)
        self._max_persisted_events = max(int(max_persisted_events or 0), self._recent_events_per_topic)
        self._persistent_db_path = Path(persistent_db_path) if persistent_db_path else None

        if self._persistent_db_path is not None:
            self._init_event_store()
            self._load_event_store_snapshot()

    def subscribe(self, topic: str, callback: EventCallback) -> int:
        with self._lock:
            self._next_id += 1
            subscriber_id = self._next_id
            normalized_topic = str(topic)
            self._subscribers.setdefault(normalized_topic, {})[subscriber_id] = callback
            self._ensure_topic_stats(normalized_topic)
            return subscriber_id

    def unsubscribe(self, topic: str, subscriber_id: int) -> None:
        with self._lock:
            normalized_topic = str(topic)
            topic_subscribers = self._subscribers.get(normalized_topic, {})
            topic_subscribers.pop(subscriber_id, None)
            if not topic_subscribers and normalized_topic in self._subscribers:
                del self._subscribers[normalized_topic]

    def publish(self, topic: str, payload: Dict[str, Any]) -> int:
        with self._lock:
            normalized_topic = str(topic)
            payload_copy = deepcopy(dict(payload or {}))
            event_record = self._build_event_record(normalized_topic, payload_copy)
            event_id = self._store_event(event_record)
            event_record["event_id"] = event_id
            payload_copy["event_id"] = event_id
            callbacks = list(self._subscribers.get(normalized_topic, {}).items())
            stats = self._ensure_topic_stats(normalized_topic)
            stats["published_count"] += 1
            self._cache_recent_event(event_record)

        for subscriber_id, callback in callbacks:
            try:
                callback(deepcopy(payload_copy))
            except Exception as exc:
                self._record_callback_failure(normalized_topic, subscriber_id, exc)
                logger.exception(
                    "Event bus subscriber callback failed topic=%s subscriber_id=%s error_type=%s error=%s",
                    normalized_topic,
                    subscriber_id,
                    type(exc).__name__,
                    exc,
                )

        return event_id

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            persisted_stats = self._get_persisted_topic_stats()
            topics = sorted(
                set(self._subscribers.keys())
                | set(self._topic_stats.keys())
                | set(self._recent_events.keys())
                | set(persisted_stats.keys())
            )
            return {
                "persistent": self._persistent_db_path is not None,
                "storage_path": str(self._persistent_db_path) if self._persistent_db_path else None,
                "topics": {
                    topic: {
                        "subscriber_count": len(self._subscribers.get(topic, {})),
                        "published_count": int(
                            persisted_stats.get(topic, {}).get(
                                "published_count",
                                self._topic_stats.get(topic, {}).get("published_count", 0),
                            )
                        ),
                        "callback_failures": int(self._topic_stats.get(topic, {}).get("callback_failures", 0)),
                        "recent_event_count": int(
                            persisted_stats.get(topic, {}).get(
                                "recent_event_count",
                                len(self._recent_events.get(topic, ())),
                            )
                        ),
                        "last_event_id": int(
                            persisted_stats.get(topic, {}).get(
                                "last_event_id",
                                self._latest_cached_event_id(topic),
                            )
                            or 0
                        ),
                        "last_failure": dict(self._topic_stats.get(topic, {}).get("last_failure") or {}) or None,
                    }
                    for topic in topics
                },
            }

    def get_recent_events(self, topic: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        normalized_topic = str(topic).strip() if topic else None
        safe_limit = max(int(limit or 0), 1)

        if self._persistent_db_path is not None:
            return self._read_events(normalized_topic, limit=safe_limit, descending=True)

        with self._lock:
            if normalized_topic:
                events = list(self._recent_events.get(normalized_topic, ()))
            else:
                events = []
                for topic_events in self._recent_events.values():
                    events.extend(topic_events)

        events.sort(key=lambda item: int(item.get("event_id") or 0), reverse=True)
        return [deepcopy(item) for item in events[:safe_limit]]

    def get_events_after(
        self,
        topic: str | None = None,
        last_event_id: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_topic = str(topic).strip() if topic else None
        safe_event_id = max(int(last_event_id or 0), 0)
        safe_limit = max(min(int(limit or 0), 1000), 1)

        if self._persistent_db_path is not None:
            return self._read_events(
                normalized_topic,
                limit=safe_limit,
                descending=False,
                after_event_id=safe_event_id,
            )

        events = self.get_recent_events(topic=normalized_topic, limit=safe_limit)
        events = [event for event in events if int(event.get("event_id") or 0) > safe_event_id]
        events.sort(key=lambda item: int(item.get("event_id") or 0))
        return events[:safe_limit]

    def clear_persisted_events(self) -> None:
        """Delete persisted events. Intended for tests and maintenance tools."""
        with self._lock:
            self._recent_events.clear()
            self._next_event_id = 0
            if self._persistent_db_path is None:
                return
            with self._connect() as conn:
                conn.execute("DELETE FROM event_bus_events")
                conn.commit()

    def _ensure_topic_stats(self, topic: str) -> dict[str, Any]:
        return self._topic_stats.setdefault(
            str(topic),
            {
                "published_count": 0,
                "callback_failures": 0,
                "last_failure": None,
            },
        )

    def _record_callback_failure(self, topic: str, subscriber_id: int, exc: Exception) -> None:
        with self._lock:
            stats = self._ensure_topic_stats(topic)
            stats["callback_failures"] += 1
            stats["last_failure"] = {
                "timestamp": datetime.now().isoformat(),
                "subscriber_id": int(subscriber_id),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    def _build_event_record(self, topic: str, payload: Dict[str, Any]) -> dict[str, Any]:
        timestamp = str(
            payload.get("timestamp")
            or payload.get("event_time")
            or datetime.now().isoformat()
        )
        event_type = str(payload.get("event_type") or payload.get("type") or "")
        status = str(payload.get("status") or "")
        message = str(payload.get("message") or "")

        if not message:
            order_payload = payload.get("order")
            if isinstance(order_payload, dict):
                status = status or str(order_payload.get("status") or "")
                message = str(order_payload.get("message") or "")

        return {
            "event_id": None,
            "topic": topic,
            "event_type": event_type,
            "status": status,
            "message": message,
            "timestamp": timestamp,
            "cached_at": datetime.now().isoformat(),
            "payload": deepcopy(payload),
        }

    def _cache_recent_event(self, event_record: Dict[str, Any]) -> None:
        topic = str(event_record.get("topic") or "")
        recent_events = self._recent_events.setdefault(topic, deque(maxlen=self._recent_events_per_topic))
        recent_events.appendleft(deepcopy(event_record))
        self._next_event_id = max(self._next_event_id, int(event_record.get("event_id") or 0))

    def _latest_cached_event_id(self, topic: str) -> int:
        events = self._recent_events.get(topic, ())
        if not events:
            return 0
        return max(int(event.get("event_id") or 0) for event in events)

    def _connect(self) -> sqlite3.Connection:
        if self._persistent_db_path is None:
            raise RuntimeError("event bus persistence is disabled")
        self._persistent_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._persistent_db_path), timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_event_store(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_bus_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    event_type TEXT,
                    status TEXT,
                    message TEXT,
                    timestamp DATETIME NOT NULL,
                    cached_at DATETIME NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_bus_topic_event_id
                ON event_bus_events (topic, event_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_bus_cached_at
                ON event_bus_events (cached_at)
                """
            )
            conn.commit()

    def _store_event(self, event_record: Dict[str, Any]) -> int:
        if self._persistent_db_path is None:
            self._next_event_id += 1
            return self._next_event_id

        row = {
            "topic": str(event_record.get("topic") or ""),
            "event_type": str(event_record.get("event_type") or ""),
            "status": str(event_record.get("status") or ""),
            "message": str(event_record.get("message") or ""),
            "timestamp": str(event_record.get("timestamp") or datetime.now().isoformat()),
            "cached_at": str(event_record.get("cached_at") or datetime.now().isoformat()),
            "payload_json": json.dumps(event_record.get("payload") or {}, ensure_ascii=False, sort_keys=True, default=str),
        }
        placeholders = ",".join(["?"] * len(self.EVENT_COLUMNS))
        sql = f"INSERT INTO event_bus_events ({','.join(self.EVENT_COLUMNS)}) VALUES ({placeholders})"

        try:
            with self._connect() as conn:
                cursor = conn.execute(sql, [row[column] for column in self.EVENT_COLUMNS])
                event_id = int(cursor.lastrowid)
                self._cleanup_persisted_events(conn)
                conn.commit()
                self._next_event_id = max(self._next_event_id, event_id)
                return event_id
        except Exception:
            logger.exception("Failed to persist event bus event topic=%s", row["topic"])
            self._next_event_id += 1
            return self._next_event_id

    def _cleanup_persisted_events(self, conn: sqlite3.Connection) -> None:
        if self._max_persisted_events <= 0:
            return
        conn.execute(
            """
            DELETE FROM event_bus_events
            WHERE event_id NOT IN (
                SELECT event_id
                FROM event_bus_events
                ORDER BY event_id DESC
                LIMIT ?
            )
            """,
            (self._max_persisted_events,),
        )

    def _load_event_store_snapshot(self) -> None:
        events = self._read_events(topic=None, limit=self._recent_events_per_topic * 20, descending=True)
        with self._lock:
            for event in reversed(events):
                self._cache_recent_event(event)
            for topic, count in self._read_published_counts().items():
                stats = self._ensure_topic_stats(topic)
                stats["published_count"] = max(int(stats.get("published_count", 0)), int(count))

    def _read_events(
        self,
        topic: str | None,
        *,
        limit: int,
        descending: bool,
        after_event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if self._persistent_db_path is None:
            return []

        clauses = []
        params: list[Any] = []
        if topic:
            clauses.append("topic = ?")
            params.append(str(topic))
        if after_event_id is not None:
            clauses.append("event_id > ?")
            params.append(int(after_event_id))

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_direction = "DESC" if descending else "ASC"
        params.append(int(limit))
        sql = f"""
            SELECT *
            FROM event_bus_events
            {where_clause}
            ORDER BY event_id {order_direction}
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, params).fetchall()
        except Exception:
            logger.exception("Failed to read event bus events topic=%s", topic)
            return []

        return [self._row_to_event(row) for row in rows]

    def _read_published_counts(self) -> dict[str, int]:
        if self._persistent_db_path is None:
            return {}
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT topic, COUNT(*) AS published_count FROM event_bus_events GROUP BY topic"
                ).fetchall()
        except Exception:
            logger.exception("Failed to read event bus published counts")
            return {}
        return {str(topic): int(count) for topic, count in rows}

    def _get_persisted_topic_stats(self) -> dict[str, dict[str, int]]:
        if self._persistent_db_path is None:
            return {}
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT topic, COUNT(*) AS published_count, MAX(event_id) AS last_event_id
                    FROM event_bus_events
                    GROUP BY topic
                    """
                ).fetchall()
        except Exception:
            logger.exception("Failed to read event bus persisted stats")
            return {}
        return {
            str(topic): {
                "published_count": int(published_count or 0),
                "recent_event_count": int(published_count or 0),
                "last_event_id": int(last_event_id or 0),
            }
            for topic, published_count, last_event_id in rows
        }

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        return {
            "event_id": int(row["event_id"]),
            "topic": str(row["topic"] or ""),
            "event_type": str(row["event_type"] or ""),
            "status": str(row["status"] or ""),
            "message": str(row["message"] or ""),
            "timestamp": str(row["timestamp"] or ""),
            "cached_at": str(row["cached_at"] or ""),
            "payload": payload,
        }


EVENT_TOPIC_ORDERS = "orders"
EVENT_TOPIC_SYSTEM = "system"

# The application singleton is durable. Unit tests can still instantiate EventBus()
# without persistence when they need an isolated in-memory bus.
event_bus = EventBus(persistent_db_path=_default_event_bus_db_path())
