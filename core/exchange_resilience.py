"""Exchange connection resilience helpers."""

from __future__ import annotations

import functools
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


@dataclass
class RetryConfig:
    """Exponential-backoff retry settings."""

    max_retries: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError, OSError)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 15.0
    consecutive_successes_to_close: int = 1


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""


class MaxRetriesExceededError(Exception):
    """Raised when a retryable call exhausts all attempts."""


class CircuitBreaker:
    """Simple circuit breaker for remote exchange endpoints."""

    def __init__(self, config: CircuitBreakerConfig | None = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.opened_at = 0.0

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self._before_call()
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def _before_call(self) -> None:
        if self.state != CircuitState.OPEN:
            return
        elapsed = time.time() - self.opened_at
        if elapsed >= self.config.recovery_timeout_seconds:
            self.state = CircuitState.HALF_OPEN
            self.success_count = 0
            return
        remaining = max(self.config.recovery_timeout_seconds - elapsed, 0.0)
        raise CircuitBreakerOpenError(f"circuit breaker is open; retry after {remaining:.1f}s")

    def _on_success(self) -> None:
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.consecutive_successes_to_close:
                self.state = CircuitState.CLOSED
                self.success_count = 0

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.opened_at = 0.0

    def health(self) -> dict[str, Any]:
        last_failure = ""
        if self.last_failure_time:
            last_failure = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_failure_time))
        return {
            "state": self.state.value,
            "failures": self.failure_count,
            "last_failure_at": last_failure,
        }


def with_retry(
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    fallback: Callable[[], Any] | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
):
    """Decorate a call with retry, circuit-breaker, and optional fallback."""
    cfg = config or RetryConfig()

    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    if circuit_breaker is not None:
                        return circuit_breaker.call(func, *args, **kwargs)
                    return func(*args, **kwargs)
                except CircuitBreakerOpenError:
                    if fallback is not None:
                        return fallback()
                    raise
                except cfg.retryable_exceptions as exc:
                    last_exception = exc
                    if attempt >= cfg.max_retries:
                        if fallback is not None:
                            return fallback()
                        raise MaxRetriesExceededError(f"max retries exceeded: {cfg.max_retries}") from exc
                    if on_retry is not None:
                        on_retry(exc, attempt + 1)
                    delay = min(cfg.base_delay_seconds * (cfg.backoff_multiplier**attempt), cfg.max_delay_seconds)
                    if cfg.jitter:
                        delay *= 0.5 + random.random()
                    if delay > 0:
                        time.sleep(delay)
                except Exception:
                    raise
            if fallback is not None:
                return fallback()
            raise MaxRetriesExceededError(f"max retries exceeded: {cfg.max_retries}") from last_exception

        return wrapper

    return decorator


def retry_call(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    fallback: Callable[[], Any] | None = None,
    **kwargs: Any,
) -> Any:
    return with_retry(config=config, circuit_breaker=circuit_breaker, fallback=fallback)(func)(*args, **kwargs)
