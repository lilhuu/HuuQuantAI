"""Runtime observability helpers for the API layer."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Dict


class APIMetricsCollector:
    """Track lightweight in-memory request metrics for the local API server."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started_at = datetime.now()
        self._active_requests = 0
        self._completed_requests = 0
        self._error_responses = 0
        self._total_duration_ms = 0.0
        self._max_duration_ms = 0.0
        self._last_request_at: str | None = None

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1

    def request_finished(self, duration_ms: float, status_code: int) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._completed_requests += 1
            if int(status_code) >= 400:
                self._error_responses += 1
            self._total_duration_ms += max(0.0, float(duration_ms))
            self._max_duration_ms = max(self._max_duration_ms, float(duration_ms))
            self._last_request_at = datetime.now().isoformat()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            average = (
                self._total_duration_ms / self._completed_requests
                if self._completed_requests > 0
                else 0.0
            )
            return {
                "started_at": self._started_at.isoformat(),
                "uptime_seconds": max(
                    0.0,
                    (datetime.now() - self._started_at).total_seconds(),
                ),
                "request_metrics": {
                    "total_requests": int(self._completed_requests),
                    "active_requests": int(self._active_requests),
                    "error_responses": int(self._error_responses),
                    "avg_duration_ms": float(average),
                    "max_duration_ms": float(self._max_duration_ms),
                    "last_request_at": self._last_request_at,
                },
            }


api_metrics = APIMetricsCollector()
