from __future__ import annotations

from typing import Protocol


class StoragePort(Protocol):
    async def presign_put(self, *, path: str, content_type: str) -> str: ...

    async def presign_get(self, *, path: str) -> str: ...
