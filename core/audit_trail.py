"""Decision audit trail for strategy and execution pipelines."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from core.sqlite_utils import configure_sqlite_connection


class AuditStage(str, Enum):
    MACRO_GATE = "macro_gate"
    REGIME_CHECK = "regime_check"
    SIGNAL_GENERATION = "signal_generation"
    REGIME_FILTER = "regime_filter"
    CONFLICT_RESOLUTION = "conflict_resolution"
    CORRELATION_FILTER = "correlation_filter"
    POSITION_SIZING = "position_sizing"
    ORDER_SIMULATION = "order_simulation"
    FILL_CONFIRMATION = "fill_confirmation"


class AuditVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ADJUST = "adjust"
    SKIP = "skip"


@dataclass
class AuditStep:
    stage: AuditStage
    verdict: AuditVerdict
    timestamp: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditTrail:
    trail_id: str
    symbol: str
    timeframe: str
    strategy_id: str
    trigger_time: str
    steps: list[AuditStep] = field(default_factory=list)
    final_decision: str = ""
    final_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trail_id": self.trail_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy_id": self.strategy_id,
            "trigger_time": self.trigger_time,
            "steps": [
                {
                    "stage": step.stage.value,
                    "verdict": step.verdict.value,
                    "timestamp": step.timestamp,
                    "inputs": step.inputs,
                    "outputs": step.outputs,
                    "reason": step.reason,
                    "duration_ms": step.duration_ms,
                    "metadata": step.metadata,
                }
                for step in self.steps
            ],
            "final_decision": self.final_decision,
            "final_reason": self.final_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class AuditMemoryStore:
    def __init__(self, max_trails: int = 10000):
        self.max_trails = max(1, int(max_trails or 10000))
        self._trails: list[AuditTrail] = []

    def save(self, trail: AuditTrail) -> None:
        self._trails.append(trail)
        if len(self._trails) > self.max_trails:
            self._trails = self._trails[-self.max_trails :]

    def get_recent(self, limit: int = 100) -> list[AuditTrail]:
        return self._trails[-max(1, int(limit or 100)) :]

    def get_by_symbol(self, symbol: str, limit: int = 100) -> list[AuditTrail]:
        return [trail for trail in self._trails if trail.symbol == symbol][-max(1, int(limit or 100)) :]


class AuditSQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        path = Path(self.db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._setup()

    def save(self, trail: AuditTrail) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_trails
                    (trail_id, symbol, timeframe, strategy_id, trigger_time, final_decision, final_reason, trail_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trail.trail_id,
                    trail.symbol,
                    trail.timeframe,
                    trail.strategy_id,
                    trail.trigger_time,
                    trail.final_decision,
                    trail.final_reason,
                    trail.to_json(),
                ),
            )

    def get_recent(self, limit: int = 100) -> list[AuditTrail]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT trail_json FROM audit_trails ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit or 100)),),
            ).fetchall()
        return [self._from_json(row["trail_json"]) for row in rows]

    def get_by_symbol(self, symbol: str, limit: int = 100) -> list[AuditTrail]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trail_json
                FROM audit_trails
                WHERE symbol = ?
                ORDER BY trigger_time DESC
                LIMIT ?
                """,
                (str(symbol or ""), max(1, int(limit or 100))),
            ).fetchall()
        return [self._from_json(row["trail_json"]) for row in rows]

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_trails (
                    trail_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    final_decision TEXT NOT NULL,
                    final_reason TEXT DEFAULT '',
                    trail_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_audit_trails_symbol_time
                    ON audit_trails(symbol, trigger_time DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        configure_sqlite_connection(conn)
        conn.row_factory = sqlite3.Row
        return conn

    def _from_json(self, payload: str) -> AuditTrail:
        data = json.loads(payload)
        trail = AuditTrail(
            trail_id=data.get("trail_id", ""),
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", ""),
            strategy_id=data.get("strategy_id", ""),
            trigger_time=data.get("trigger_time", ""),
            final_decision=data.get("final_decision", ""),
            final_reason=data.get("final_reason", ""),
        )
        for step_data in data.get("steps", []):
            trail.steps.append(
                AuditStep(
                    stage=AuditStage(step_data.get("stage", AuditStage.SIGNAL_GENERATION.value)),
                    verdict=AuditVerdict(step_data.get("verdict", AuditVerdict.PASS.value)),
                    timestamp=step_data.get("timestamp", ""),
                    inputs=step_data.get("inputs", {}) or {},
                    outputs=step_data.get("outputs", {}) or {},
                    reason=step_data.get("reason", ""),
                    duration_ms=float(step_data.get("duration_ms", 0) or 0),
                    metadata=step_data.get("metadata", {}) or {},
                )
            )
        return trail


class AuditLogger:
    def __init__(self, store: AuditMemoryStore | AuditSQLiteStore | None = None):
        self.store = store or AuditMemoryStore()

    def create_trail(self, symbol: str, timeframe: str, strategy_id: str) -> AuditTrail:
        now = datetime.now(timezone.utc).isoformat()
        millis = int(time.time() * 1000)
        return AuditTrail(
            trail_id=f"AUDIT_{symbol.replace('/', '')}_{strategy_id}_{millis}",
            symbol=symbol,
            timeframe=timeframe,
            strategy_id=strategy_id,
            trigger_time=now,
        )

    def log_step(
        self,
        trail: AuditTrail,
        stage: AuditStage,
        verdict: AuditVerdict,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        reason: str = "",
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> AuditTrail:
        trail.steps.append(
            AuditStep(
                stage=stage,
                verdict=verdict,
                timestamp=datetime.now(timezone.utc).isoformat(),
                inputs=inputs or {},
                outputs=outputs or {},
                reason=reason,
                duration_ms=round(float(duration_ms or 0), 4),
                metadata=metadata or {},
            )
        )
        return trail

    def finalize(self, trail: AuditTrail, decision: str, reason: str) -> AuditTrail:
        trail.final_decision = str(decision or "")
        trail.final_reason = str(reason or "")
        self.store.save(trail)
        return trail
