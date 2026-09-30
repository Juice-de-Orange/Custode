"""HTTP contracts for ``links`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LinkCreate(BaseModel):
    """Link two objects. Order is irrelevant — the endpoints are canonicalised server-side, so
    ``(a, b)`` and ``(b, a)`` reference the same link."""

    a_type: str = Field(min_length=1, max_length=40)
    a_id: uuid.UUID
    b_type: str = Field(min_length=1, max_length=40)
    b_id: uuid.UUID
    relation: str = Field(default="related", min_length=1, max_length=40)


class LinkResponse(BaseModel):
    """One link between two objects (endpoints in canonical order)."""

    id: uuid.UUID
    src_type: str
    src_id: uuid.UUID
    dst_type: str
    dst_id: uuid.UUID
    relation: str
    created_at: datetime
