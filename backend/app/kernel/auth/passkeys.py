"""Passkey (WebAuthn) credentials (KONZEPT §8). One row per registered authenticator,
keyed by ``credential_id`` (base64url). The COSE ``public_key`` + a monotonic ``sign_count``
verify each assertion. Owned by the user (RLS ``user_id = app.user_id`` for register/list/
delete); the passwordless login looks a credential up cross-user by ``credential_id`` as
``custode_maint`` (before the acting user is known)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class Passkey(Base):
    __tablename__ = "auth_passkeys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    credential_id: Mapped[str] = mapped_column(String(512), unique=True)  # base64url
    public_key: Mapped[str] = mapped_column(Text)  # base64url of the COSE key bytes
    sign_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    name: Mapped[str] = mapped_column(String(120), server_default=text("''"))
    transports: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
