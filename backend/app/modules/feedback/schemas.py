"""HTTP contracts for ``feedback`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackCategory = Literal["bug", "idea", "praise", "other"]


class DiagnosticEntry(BaseModel):
    """One technical breadcrumb from the client ring buffer. **No content/PII** — only the route
    the user was on, the error-reference short-code (ARCHITECTURE §12) and the HTTP status."""

    model_config = {"extra": "forbid"}

    at: str = Field(max_length=40)  # ISO timestamp (client clock)
    route: str | None = Field(default=None, max_length=120)
    error_ref: str | None = Field(default=None, max_length=64)
    status: int | None = Field(default=None, ge=0, le=599)


class FeedbackDiagnostics(BaseModel):
    """Strictly opt-in diagnostics attachment (KONZEPT §5.12): app version + a bounded ring buffer
    of recent error breadcrumbs. Bounded length keeps the payload small and carries **no** message
    content. ``extra="forbid"`` so a client cannot smuggle arbitrary data through."""

    model_config = {"extra": "forbid"}

    app_version: str = Field(max_length=40)
    entries: list[DiagnosticEntry] = Field(default_factory=list, max_length=25)


class FeedbackCreate(BaseModel):
    """Submit feedback: a category plus a free-text message, optionally tagged with the
    error-reference short-code the user saw, the route they were on, and an opt-in diagnostics
    attachment (technical breadcrumbs only, never content)."""

    category: FeedbackCategory
    message: str = Field(min_length=1, max_length=5000)
    error_ref: str | None = Field(default=None, max_length=64)
    route: str | None = Field(default=None, max_length=120)
    diagnostics: FeedbackDiagnostics | None = None


class FeedbackResponse(BaseModel):
    """One feedback submission (the caller's own, newest first)."""

    id: uuid.UUID
    category: FeedbackCategory
    message: str
    error_ref: str | None
    route: str | None
    created_at: datetime
