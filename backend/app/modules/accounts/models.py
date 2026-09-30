from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class User(Base):
    """Global identity (KONZEPT §10). NOT household-scoped — one user ↔ n households.
    RLS (migration 0002): visible to self or co-members of the active household."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Child accounts (S12): household-unique username + Argon2id-hashed PIN; NULL for adults.
    username: Mapped[str | None] = mapped_column(String(50))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    # TOTP-2FA (KONZEPT §8.5): base32 secret + enabled flag. Secret is reversible
    # (unlike the password hash); RLS-protected today, encryption-at-rest is a follow-up.
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # E-mail verification (S9b): set when the user confirms their address; NULL = unverified.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str] = mapped_column(String(100))
    locale: Mapped[str] = mapped_column(String(10), server_default=text("'de'"))
    # Self-service profile blob (S11): work hours, dietary prefs, notification settings.
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # „Zur Löschung vorgemerkt" (11-S1c setzt es sofort, die Karenz läuft ab hier).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # „Endgültig ausgeräumt" (11-S1d). Bewusst eine zweite Spalte: `deleted_at` kann nicht zugleich
    # beides heißen, sonst sähe ein zweiter Purge-Lauf dieselbe Zeile wieder als fällig.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Household(Base):
    """Tenant root. RLS: id = app.household_id."""

    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    name: Mapped[str] = mapped_column(String(120))
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tz: Mapped[str] = mapped_column(String(40), server_default=text("'Europe/Vienna'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(HouseholdScoped, Base):
    """User ↔ household with role. RLS: household_id = app.household_id."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("household_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # admin|member|child|guest


class Invite(HouseholdScoped, Base):
    """Household invite (code/link, time-limited). RLS: household_id = app.household_id."""

    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(10), server_default=text("'member'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    uses: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Consent(Base):
    """Append-only consent ledger (KONZEPT §5.1 children, §5.15 wearables). One row per consent
    DECISION; never updated/deleted — the app role has only SELECT + INSERT. RLS (migration 0013):
    household_id = app.household_id.

    ``action`` (migration 0068) makes withdrawal expressible: a revoke is a NEW row, so the
    ledger stays append-only. The effective state per type is therefore a fold ("latest row per
    type wins", ``service.effective_consents``), never a column read. ``granted_by`` is the
    ACTOR — the one who granted OR revoked."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    subject_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(10), server_default=text("'grant'"))
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
