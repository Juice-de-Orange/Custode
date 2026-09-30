"""HTTP contracts for ``guides`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GuideCreate(BaseModel):
    """Create a guide: a title plus optional markdown body, category, tags and a contact member."""

    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=200000)
    category: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list)
    contact_id: uuid.UUID | None = None


class GuideUpdate(BaseModel):
    """Patch a guide (PATCH + If-Match). All fields optional; only the present ones change. Sending
    ``contact_id: null`` clears the contact (presence is read via ``model_fields_set``)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=200000)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None
    contact_id: uuid.UUID | None = None


class GuideSummary(BaseModel):
    """List item: no body (kept light for the list/search view)."""

    id: uuid.UUID
    title: str
    category: str
    tags: list[str]
    contact_id: uuid.UUID | None
    updated_at: datetime


class GuideResponse(BaseModel):
    """Full guide incl. markdown body."""

    id: uuid.UUID
    title: str
    body_md: str
    category: str
    tags: list[str]
    contact_id: uuid.UUID | None
    author_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AttachmentResponse(BaseModel):
    """Metadata of a guide attachment. The bytes live in blob storage and are fetched separately
    (``GET …/attachments/{id}``); the response never carries them."""

    id: uuid.UUID
    guide_id: uuid.UUID
    filename: str
    content_type: str
    byte_size: int
    uploaded_by: uuid.UUID
    created_at: datetime
