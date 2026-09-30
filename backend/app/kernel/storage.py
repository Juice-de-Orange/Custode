"""Pluggable blob storage for user uploads (recipe photos, …). Filesystem-backed on the single-host
deploy; the ``Storage`` protocol keeps S3/MinIO swappable later. A Null backend (nothing configured)
disables uploads **gracefully** (Graceful Enhancement) — callers check ``enabled`` first.

Keys are always server-generated (never user input) and sanitized to the final path segment, so a
filesystem backend can't be tricked into path traversal."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.settings import get_settings


class Storage(Protocol):
    enabled: bool

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> None: ...


class NullStorage:
    """No backend configured: uploads are unavailable, reads return nothing."""

    enabled = False

    def put(self, key: str, data: bytes) -> None:
        raise RuntimeError("storage backend not configured")

    def get(self, key: str) -> bytes | None:
        return None

    def delete(self, key: str) -> None:
        return None


class FilesystemStorage:
    """Store blobs as files under a root directory (one persistent volume on the host)."""

    enabled = True

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are server-generated; take the last path segment defensively (no traversal).
        safe = key.replace("\\", "/").split("/")[-1]
        if not safe or safe in {".", ".."}:
            raise ValueError("invalid storage key")
        return self._root / safe

    def put(self, key: str, data: bytes) -> None:
        self._path(key).write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache
def get_storage() -> Storage:
    storage_dir = get_settings().storage_dir
    return FilesystemStorage(Path(storage_dir)) if storage_dir else NullStorage()
