from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class Operator(Base):
    """A Betreiber-Konsole operator (ADR-0015). A **separate** identity space from ``users`` — NO
    ``household_id``, NO RLS (tenant isolation is meaningless here). Auth = password + mandatory
    TOTP (Passkey folgt). Only the ops DB roles may read this table; ``custode_app`` is revoked
    (migration 0056). Deactivation via ``is_active`` (not soft-delete)."""

    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatorPasskey(Base):
    """A WebAuthn credential for an operator (ADR-0072-Erweiterung). Mirrors ``auth_passkeys`` but
    keyed by ``operator_id`` and with NO RLS (operators have no household). One row per device;
    ``credential_id`` (base64url) is unique, ``public_key`` (COSE) + monotonic ``sign_count`` verify
    each assertion. Read on ops_readonly (list + pre-auth login lookup), written on ops_actions."""

    __tablename__ = "operator_passkeys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    credential_id: Mapped[str] = mapped_column(String(512), unique=True)  # base64url
    public_key: Mapped[str] = mapped_column(Text)  # base64url of the COSE key bytes
    sign_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    name: Mapped[str] = mapped_column(String(120), server_default=text("''"))
    transports: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Banner(Base):
    """A global operator banner (maintenance notice etc.). Ops-managed (audited), app-displayed.
    NO ``household_id`` (global). ``custode_app`` may only read active banners; writes are
    ``ops_actions`` only (migration 0058)."""

    __tablename__ = "ops_banners"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    message: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(10), server_default=text("'info'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
