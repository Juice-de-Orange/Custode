from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Feedback(HouseholdScoped, Base):
    """A piece of user feedback from the Friends&Family beta (Roadmap Phase 8, „Feedback-Kanal").
    ``category`` is a small fixed set (bug/idea/praise/other); ``message`` is free text.
    ``error_ref`` optionally carries the copyable error-reference short-code the user saw
    (ARCHITECTURE §12) so support can jump straight to the trace; ``route`` is where they were.
    RLS: household_id. The ops console reads these later (P8-S8) — never the raw fact table, only
    via an aggregate/action surface."""

    __tablename__ = "feedback"

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    error_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Optional, strictly opt-in diagnostics attachment (KONZEPT §5.12): app version + a small ring
    # buffer of recent error-reference codes / routes the client saw. **Never content/PII** — only
    # structured technical breadcrumbs the client collected for support. Shape: see schemas.
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
