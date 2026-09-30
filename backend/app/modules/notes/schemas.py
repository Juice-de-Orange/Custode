"""HTTP contracts for ``notes`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    """Create a note: a title plus optional markdown body; ``pinned`` defaults off."""

    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=50000)
    pinned: bool = False


class NoteUpdate(BaseModel):
    """Patch a note (PATCH + If-Match). All fields optional; only the present ones change."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=50000)
    pinned: bool | None = None


class NoteSummary(BaseModel):
    """List item: no body (kept light for the list view)."""

    id: uuid.UUID
    title: str
    pinned: bool
    author_id: uuid.UUID
    updated_at: datetime


class NoteResponse(BaseModel):
    """Full note incl. markdown body."""

    id: uuid.UUID
    title: str
    body_md: str
    pinned: bool
    author_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TrashedNote(BaseModel):
    """A soft-deleted note in the trash (P8-S4). ``deleted_at`` lets the UI show how long it has
    left before the retention reaper purges it for good (30-day window, P8-S3)."""

    id: uuid.UUID
    title: str
    deleted_at: datetime


class NoteVersionResponse(BaseModel):
    """An archived previous version of a note (P7-S2, newest first; max 5 kept)."""

    version_no: int
    title: str
    body_md: str
    edited_by: uuid.UUID
    created_at: datetime


class ToTaskResult(BaseModel):
    """The personal task created from a note („Konvertieren-zu", P7-S3, ADR-0061)."""

    task_id: uuid.UUID
    title: str
