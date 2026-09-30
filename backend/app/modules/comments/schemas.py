"""HTTP contracts for ``comments`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    """Post a comment on an object (``object_type`` + ``object_id``)."""

    object_type: str = Field(min_length=1, max_length=40)
    object_id: uuid.UUID
    body_md: str = Field(min_length=1, max_length=10000)


class CommentUpdate(BaseModel):
    """Edit a comment's body (author only, PATCH + If-Match). Only ``body_md`` is mutable."""

    body_md: str = Field(min_length=1, max_length=10000)


class CommentResponse(BaseModel):
    """One comment on an object, oldest-first in the thread. ``version`` is the ETag for editing —
    the thread carries it so the client can PATCH inline (If-Match) without a per-comment GET."""

    id: uuid.UUID
    object_type: str
    object_id: uuid.UUID
    author_id: uuid.UUID
    body_md: str
    version: int
    created_at: datetime
    updated_at: datetime
