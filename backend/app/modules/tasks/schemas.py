"""HTTP request/response contracts for ``tasks`` (single source for the OpenAPI schema -> web zod
client). Separate from the ORM models. Points stay inert in P4-S1 (no ledger, ADR-0034)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Rotation = Literal["fair", "fixed", "open"]
TaskStatus = Literal["open", "done", "expired", "armed"]


class TaskTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    points: int = Field(default=0, ge=0, le=100000)
    duration_est_minutes: int | None = Field(default=None, ge=0, le=100000)
    outdoor: bool = False
    rotation: Rotation = "open"
    room_id: uuid.UUID | None = None


class TaskTemplateUpdate(BaseModel):
    """Partial update (If-Match)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    points: int | None = Field(default=None, ge=0, le=100000)
    duration_est_minutes: int | None = Field(default=None, ge=0, le=100000)
    outdoor: bool | None = None
    rotation: Rotation | None = None
    room_id: uuid.UUID | None = None


class TaskTemplateResponse(BaseModel):
    """A task template; ``version`` is the ETag for If-Match optimistic concurrency."""

    id: uuid.UUID
    title: str
    description: str | None
    points: int
    duration_est_minutes: int | None
    outdoor: bool
    rotation: Rotation
    room_id: uuid.UUID | None
    version: int


class TaskTemplateSummary(BaseModel):
    """Lightweight list-card view."""

    id: uuid.UUID
    title: str
    points: int
    outdoor: bool
    rotation: Rotation
    room_id: uuid.UUID | None


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=40)
    decay_days: int = Field(gt=0, le=3650)


class RoomUpdate(BaseModel):
    """Partial update (If-Match)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=40)
    decay_days: int | None = Field(default=None, gt=0, le=3650)


class RoomResponse(BaseModel):
    id: uuid.UUID
    name: str
    icon: str | None
    decay_days: int
    version: int


class RoomHeatmapEntry(BaseModel):
    """A room's computed freshness for the heatmap (KONZEPT §5.9): status from last completion +
    ``decay_days``; never stored."""

    room_id: uuid.UUID
    name: str
    icon: str | None
    decay_days: int
    last_done: datetime | None
    status: Literal["green", "amber", "red"]


class TaskInstanceCreate(BaseModel):
    """Create an instance from a template (``template_id`` set -> title/points snapshotted) OR
    ad-hoc (``template_id`` null -> ``title`` required)."""

    template_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    assigned_to: uuid.UUID | None = None
    due_at: datetime | None = None
    room_id: uuid.UUID | None = None  # optional direct room (ad-hoc tasks, S-13)


class TaskInstanceResponse(BaseModel):
    """A task instance; ``version`` is the ETag for the complete action's If-Match."""

    id: uuid.UUID
    template_id: uuid.UUID | None
    title: str
    points: int
    assigned_to: uuid.UUID | None
    due_at: datetime | None
    status: TaskStatus
    done_at: datetime | None
    done_by: uuid.UUID | None
    awarded_points: int | None  # effective (decayed) points credited; None until done
    room_id: uuid.UUID | None
    version: int
