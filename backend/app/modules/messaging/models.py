from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Letter(HouseholdScoped, Base):
    """A household „Brief" (KONZEPT §5.12): subject + body from a member. Empty ``to_ids`` = a
    round-letter to everyone; otherwise the addressed members. RLS: household_id. ``version``
    (mixin/trigger) is the ETag. Read-status lives in ``letter_reads``."""

    __tablename__ = "letters"

    from_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    to_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    subject: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text, server_default=text("''"))


class LetterRead(Base):
    """A read receipt: one row per (letter, user) once that user has opened the letter (P7-S4,
    ADR-0062). Append-only (no mixin); unique per (letter_id, user_id). RLS: household_id."""

    __tablename__ = "letter_reads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    letter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("letters.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
