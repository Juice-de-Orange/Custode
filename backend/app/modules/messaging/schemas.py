"""HTTP contracts for ``messaging`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LetterCreate(BaseModel):
    """Write a letter. ``to_ids`` empty = a round-letter to the whole household."""

    subject: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=50000)
    to_ids: list[uuid.UUID] = Field(default_factory=list)


class LetterSummary(BaseModel):
    """Inbox list item: no body. ``read_by_me`` reflects the viewer; ``read_count`` is how many
    distinct members have opened it."""

    id: uuid.UUID
    subject: str
    from_id: uuid.UUID
    to_ids: list[uuid.UUID]
    created_at: datetime
    read_by_me: bool
    read_count: int


class LetterResponse(BaseModel):
    """A full letter incl. body. Fetching it marks it read for the viewer (if a recipient)."""

    id: uuid.UUID
    subject: str
    body_md: str
    from_id: uuid.UUID
    to_ids: list[uuid.UUID]
    created_at: datetime
    read_by_me: bool
    read_count: int


class UnreadCount(BaseModel):
    """How many letters addressed to the viewer are still unread."""

    unread: int


class LetterToTaskResult(BaseModel):
    """The personal task created from a letter („Kümmerst du dich?", P7-S5, ADR-0063)."""

    task_id: uuid.UUID
    title: str
