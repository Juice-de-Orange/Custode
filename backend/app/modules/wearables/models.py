"""wearables ORM models (Migration 0069, KONZEPT §5.15/§10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Date, DateTime, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class WearableConnection(HouseholdScoped, Base):
    """One member's link to a wearable cloud (Art. 9 GDPR, KONZEPT §5.15).

    **Member-scoped RLS** (0069): the policy predicate is ``household_id`` AND ``member_id``, so
    a co-member — including an admin — reads 0 rows at the database level. Unlike
    ``ExternalCalendarSubscription``, owner-only here is NOT a service-layer convention (N-2,
    ADR-0081). ``member_id`` is therefore always ``principal.user_id``; there is no path to
    create a connection *for* somebody else.

    ``tokens_enc`` holds exactly ONE SecretBox value (``v1:<fernet>``, ADR-0077) over the JSON
    ``{access_token, refresh_token, token_type, scopes}`` — see ``tokens.py`` for the format
    contract. ``token_expires_at`` sits OUTSIDE the ciphertext on purpose: the 9-S6 cron filters
    "expiring soon" in SQL without decrypting every row, and an expiry instant is not a secret.

    ``deleted_at`` exists via the mixin but a CHECK constraint pins it to NULL: Art. 9 demands
    deletion that actually deletes, and a tombstone that is never used would be a footgun. That
    also keeps the table out of the retention reaper's allowlist."""

    __tablename__ = "wearable_connections"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    tokens_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"))
    # Failure category slug (``refresh_failed``, ``unreachable``, …) — never a token or URL;
    # NULL = the last run was fine. Mirrors ``last_sync_error`` on CalDAV subscriptions.
    last_error: Mapped[str | None] = mapped_column(String(40))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WearableDailyRow(HouseholdScoped, Base):
    """One member's daily values from one provider (Art. 9 GDPR).

    Empty until the 9-S6 ingest cron; created in 9-S5 because the member-vs-member RLS negative
    test only makes its real statement against the health data itself, and because the deletion
    path (consent withdrawal, disconnect) has to reference it.

    Same member-scoped RLS and the same hard-delete CHECK as ``WearableConnection``. Withdrawing
    consent for a type NULLs that type's columns immediately — no soft delete, no grace period."""

    __tablename__ = "wearable_daily"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(20))
    day: Mapped[date] = mapped_column(Date)
    sleep_score: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer)
    readiness: Mapped[int | None] = mapped_column(SmallInteger)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_kcal: Mapped[int | None] = mapped_column(Integer)
    rhr: Mapped[int | None] = mapped_column(SmallInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
