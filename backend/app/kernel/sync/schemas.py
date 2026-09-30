"""Wire contracts for the Sync-Batch (ARCHITECTURE §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class SyncOp(BaseModel):
    """One offline operation. ``fields`` carries only the changed fields (per-field-group LWW);
    ``base_version`` is informational (LWW resolves conflicts, it never rejects)."""

    client_op_id: uuid.UUID
    entity: str
    id: uuid.UUID
    base_version: int = 0
    op: Literal["upsert", "delete"]
    fields: dict[str, Any] = Field(default_factory=dict)


class SyncBatchRequest(BaseModel):
    ops: Annotated[list[SyncOp], Field(max_length=500)]


class ServerEntityState(BaseModel):
    """Authoritative state after applying; the client overwrites its local copy with this."""

    entity: str
    id: uuid.UUID
    version: int
    deleted: bool
    fields: dict[str, Any]


class SyncBatchResponse(BaseModel):
    applied: list[ServerEntityState]


class SyncChange(BaseModel):
    """One delta-pull change: an upsert (current fields) or a delete (tombstone, empty fields)."""

    entity: str
    id: uuid.UUID
    op: Literal["upsert", "delete"]
    version: int
    updated_at: datetime
    fields: dict[str, Any]


class SyncPullResponse(BaseModel):
    changes: list[SyncChange]
    next_cursor: str | None = None
