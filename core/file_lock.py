"""Small cross-process file locking and atomic write helpers."""

from __future__ import annotations

from contextlib import AbstractContextManager
import os
from pathlib import Path
import time
from uuid import uuid4


class FileLockTimeout(TimeoutError):
    """Raised when a file lock cannot be acquired in time."""


class FileLock(AbstractContextManager):
    """Exclusive lock backed by a sidecar ``.lock`` file.

    The lock is intentionally exclusive for both readers and writers. Runtime
    config files are tiny, so this keeps the implementation portable and avoids
    readers observing a writer mid-update.
    """

    def __init__(
        self,
        target_path: str | os.PathLike[str],
        *,
        timeout_seconds: float = 10.0,
        poll_seconds: float = 0.05,
    ) -> None:
        self.target_path = Path(target_path)
        self.lock_path = self.target_path.with_name(f"{self.target_path.name}.lock")
        self.timeout_seconds = max(float(timeout_seconds or 0), 0.1)
        self.poll_seconds = max(float(poll_seconds or 0), 0.01)
        self._handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.lock_path.open("a+b")
        self._ensure_lock_byte()

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._lock_handle()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise FileLockTimeout(f"Timed out waiting for lock: {self.lock_path}")
                time.sleep(self.poll_seconds)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return

        try:
            self._unlock_handle()
        finally:
            self._handle.close()
            self._handle = None

    def _ensure_lock_byte(self) -> None:
        assert self._handle is not None
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"\0")
            self._handle.flush()
        self._handle.seek(0)

    def _lock_handle(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)


def read_text_locked(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    default: str | None = None,
) -> str | None:
    """Read a small text file while holding its sidecar lock."""
    target = Path(path)
    with FileLock(target):
        if not target.exists():
            return default
        return target.read_text(encoding=encoding)


def atomic_write_text_locked(
    path: str | os.PathLike[str],
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically replace a text file while holding its sidecar lock."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(target):
        temp_path = target.with_name(f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding=encoding, newline="\n") as file_obj:
                file_obj.write(content)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)
