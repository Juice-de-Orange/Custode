from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Note(HouseholdScoped, Base):
    """A household markdown note (KONZEPT §5 / Phase 7). RLS: household_id = app.household_id.
    ``version`` (from the mixin, bumped by the shared trigger) is the ETag for PATCH + If-Match.
    Convert-to / dashboard-pin view are later slices."""

    __tablename__ = "notes"

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text, server_default=text("''"))
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class NoteVersion(Base):
    """An archived snapshot of a note's previous content (P7-S2, KONZEPT §5 „5 Versionen").
    Append-only (no mixin). RLS: household_id. Only the most recent 5 per note are kept (older
    pruned on write). ``version_no`` = the note ``version`` it superseded (unique per note)."""

    __tablename__ = "note_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
