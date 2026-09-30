"""Login audit log (ARCHITECTURE §12, ADR-0025). One row per login attempt — **user-scoped**
(login is pre-household, so RLS keys on ``user_id`` like ``auth_sessions``, not
``household_id``). Stores only the country code (from an edge header); never the IP, e-mail,
or any token. ``user_id`` is NULL for an unknown e-mail (no enumeration). Written by the maint
bootstrap; a user can read their own attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base
from app.kernel.tenancy.session import maint_session


class AuthLoginEvent(Base):
    """A single login attempt. PII-free: country code only — no IP/e-mail/token."""

    __tablename__ = "auth_login_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    country_code: Mapped[str | None] = mapped_column(String(2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def record_login_event(
    *, user_id: uuid.UUID | None, success: bool, country_code: str | None
) -> None:
    """Append a login-audit row in its OWN maint transaction, so the row survives the 401
    ``raise`` on a failed attempt (the login's main transaction may roll back)."""
    async with maint_session() as session:
        session.add(AuthLoginEvent(user_id=user_id, success=success, country_code=country_code))
