from __future__ import annotations

import os
from pathlib import Path


class LockAcquisitionError(RuntimeError):
    """Raised when an apply lock is already held by another process."""


class FileLock:
    """Small atomic lock-file context manager for local mutation guards."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(str(self.path), flags, 0o644)
        except FileExistsError as exc:
            details = ""
            try:
                details = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            suffix = f" ({details})" if details else ""
            raise LockAcquisitionError(f"Apply lock already held: {self.path}{suffix}") from exc
        payload = f"pid={os.getpid()}\n"
        os.write(self._fd, payload.encode("utf-8"))
        return self

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
