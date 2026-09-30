"""Session model (KONZEPT §8.5): short-lived access tokens + rotating refresh
tokens with reuse detection.

Each row is one refresh token in a rotation *family*. On refresh the presented row
is superseded (``rotated_at`` set) and a fresh row with the same ``family_id`` is
issued. Re-presenting a token that is already rotated or revoked is a theft signal:
the whole family is revoked. Refresh tokens are stored only as a SHA-256 hash —
never in clear. Owned by the user (RLS ``user_id = app.user_id``); the cross-user
refresh lookup (by hash, before the user is known) runs as ``custode_maint``."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # Rotation family — all rotations of one login share this id (reuse detection).
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    device_label: Mapped[str] = mapped_column(String(120), server_default=text("''"))
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when this token was rotated away (consumed). Re-use after this == theft.
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
