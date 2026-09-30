from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Capture(HouseholdScoped, Base):
    """A quick-capture „Zuruf" (KONZEPT §5.17). RLS: household_id. ``raw_text`` is the member's free
    text; ``proposal_json`` is the deterministic parser's structured result (target/label/qty/…),
    ``tags`` a denormalised copy for filtering. Status machine: ``proposed`` (in the inbox) ->
    ``confirmed`` (an artifact was created) / ``dismissed``. ``auto`` is reserved for the later
    silent-execute path (LLM, Phase 7)."""

    __tablename__ = "captures"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    # proposed | confirmed | dismissed | auto (CHECK constraint in migration)
    status: Mapped[str] = mapped_column(String(12), server_default=text("'proposed'"))
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
