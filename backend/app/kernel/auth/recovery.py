"""Recovery codes (KONZEPT §8): one-time TOTP backup codes for the login fallback when
the authenticator is lost. Each row is one code, stored only as a SHA-256 hash and
single-use via ``used_at``. Owned by the user (RLS ``user_id = app.user_id``); the
cross-user consume at login (by hash, before the user is scoped) runs as ``custode_maint``."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class RecoveryCode(Base):
    __tablename__ = "auth_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
