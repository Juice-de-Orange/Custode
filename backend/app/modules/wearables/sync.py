"""Wearable ingest + retention (P9-S6, ADR-0081).

Run shape (nightly worker cron), deliberately the CalDAV-sync shape with one extra constraint:

1. Enumerate active connections under the **maint** session (SELECT-only ``maint_all``).
2. Per connection, everything else happens under the OWNER's ``scoped_session`` — the maint role
   cannot write these tables by design (member-scoped RLS, migration 0069). This is not an
   optimisation detail; it is the mechanism that makes N-2 hold for a background job.

Per connection, in this order:

* **Rollen-Nachlauf.** A member demoted to child (or removed) since the last run must not keep
  feeding a health record — Kinder haben keine Wearables (Root-CLAUDE.md). Their data is erased
  and the connection dropped. Checked BEFORE any outbound request, so a demotion also stops the
  traffic, not just the storage.
* **Refresh when due.** Providers rotate refresh tokens, so a successful refresh REPLACES
  ``tokens_enc`` wholesale. A rejected refresh is terminal until the user re-authorises →
  ``status='needs_reauth'``; we do not retry it every night.
* **Fetch + consent filter.** The adapter returns whatever the granted scopes yield; this module
  drops every value whose data type is not currently consented. The provider scope is coarser
  than our vocabulary (``daily`` covers three types), so this filter — not the OAuth scope — is
  what actually enforces per-type consent.

Failure isolation is three-tiered like the CalDAV sync: a bad field is dropped, a bad connection
records ``last_error`` and the loop continues, a bad run logs and the next tick retries. Logs
carry aggregate counts and category slugs only — never tokens, never values, never a member's
provider identity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth.context import Role
from app.kernel.crypto import SecretBox, SecretBoxError, get_secretbox
from app.kernel.ports.wearable import (
    WearableAuthError,
    WearableCloudPort,
    WearableDaily,
    WearableOAuthPort,
)
from app.kernel.tenancy.session import maint_session, scoped_session
from app.logging import get_logger
from app.modules.accounts import api as accounts_api
from app.modules.wearables.models import WearableConnection, WearableDailyRow
from app.modules.wearables.tokens import decode_tokens, encode_tokens
from app.modules.wearables.types import ALL_CONSENT_TYPES

_log = get_logger("wearables.sync")

#: Re-fetch a trailing window each run: providers finalise a night's values late and correct them
#: afterwards. Three days is enough to pick up a correction without re-reading a whole history.
INGEST_WINDOW_DAYS = 3

#: Refresh this far ahead of expiry so a token never dies mid-run.
_REFRESH_MARGIN = timedelta(minutes=30)

#: Which stored columns a consent type covers (mirrors ``service._COLUMNS_BY_CONSENT``).
_FIELDS_BY_CONSENT: dict[str, tuple[str, ...]] = {
    "wearable_sleep": ("sleep_score", "sleep_minutes"),
    "wearable_readiness": ("readiness",),
    "wearable_activity": ("steps", "active_kcal"),
    "wearable_heartrate": ("rhr",),
}

_ALL_FIELDS: tuple[str, ...] = tuple(
    field for fields in _FIELDS_BY_CONSENT.values() for field in fields
)


@dataclass
class IngestStats:
    """Aggregate outcome of one run (the only thing that is ever logged)."""

    connections: int = 0
    ingested: int = 0
    days_written: int = 0
    skipped: int = 0
    failed: int = 0
    revoked: int = 0


@dataclass(frozen=True)
class _ConnRef:
    """Detached snapshot of one connection (the maint session closes before any fetch)."""

    id: uuid.UUID
    household_id: uuid.UUID
    member_id: uuid.UUID
    provider: str
    tokens_enc: str | None
    token_expires_at: datetime | None


class _Skip(Exception):
    """This connection is skipped this run; ``category`` lands in ``last_error``."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def allowed_fields(consents: dict[str, bool]) -> set[str]:
    """The columns the member currently consents to. Absence of consent is not consent."""
    return {
        field
        for consent_type, fields in _FIELDS_BY_CONSENT.items()
        if consents.get(consent_type)
        for field in fields
    }


def consented_values(daily: WearableDaily, allowed: set[str]) -> dict[str, int | None]:
    """Project a provider result onto the consented columns.

    Every non-consented column is written as ``None``, not merely omitted: a type withdrawn
    between two runs must lose its old value, and an ``upsert`` that only touched the allowed
    fields would leave the previous night's data lying around."""
    return {field: (getattr(daily, field) if field in allowed else None) for field in _ALL_FIELDS}


async def _load_connections() -> list[_ConnRef]:
    async with maint_session() as ms:
        rows = await ms.execute(
            select(
                WearableConnection.id,
                WearableConnection.household_id,
                WearableConnection.member_id,
                WearableConnection.provider,
                WearableConnection.tokens_enc,
                WearableConnection.token_expires_at,
            )
            .where(WearableConnection.status == "active")
            .order_by(WearableConnection.created_at)
        )
        return [_ConnRef(*row) for row in rows.all()]


async def _record_error(conn: _ConnRef, category: str) -> None:
    """Stamp a failure category on the connection (best effort — never breaks the loop)."""
    try:
        async with scoped_session(
            household_id=conn.household_id, user_id=conn.member_id
        ) as session:
            row = await session.get(WearableConnection, conn.id)
            if row is not None:
                row.last_error = category[:40]
    except Exception:
        _log.warning("wearable_error_stamp_failed", connection_id=str(conn.id))


async def _mark_needs_reauth(conn: _ConnRef, category: str) -> None:
    async with scoped_session(household_id=conn.household_id, user_id=conn.member_id) as session:
        row = await session.get(WearableConnection, conn.id)
        if row is not None:
            row.status = "needs_reauth"
            row.last_error = category[:40]


async def _drop_connection(conn: _ConnRef) -> None:
    """Erase everything for a member who may no longer hold a connection (role changed)."""
    async with scoped_session(household_id=conn.household_id, user_id=conn.member_id) as session:
        await session.execute(
            delete(WearableDailyRow).where(
                WearableDailyRow.member_id == conn.member_id,
                WearableDailyRow.provider == conn.provider,
            )
        )
        row = await session.get(WearableConnection, conn.id)
        if row is not None:
            await session.delete(row)


async def _refresh_if_due(
    conn: _ConnRef, *, box: SecretBox, oauth: WearableOAuthPort, now: datetime
) -> str:
    """Return a usable access token, refreshing (and persisting) first when the stored one is
    about to expire. Raises ``_Skip`` when the connection cannot be used this run."""
    try:
        tokens = decode_tokens(box, conn.tokens_enc or "")
    except SecretBoxError as exc:
        # Wrong/rotated key or tampering — not recoverable by retrying.
        raise _Skip("tokens_undecryptable") from exc

    fresh_enough = conn.token_expires_at is None or conn.token_expires_at > now + _REFRESH_MARGIN
    if fresh_enough:
        return tokens.access_token
    if not tokens.refresh_token:
        raise _Skip("no_refresh_token")

    try:
        renewed = await oauth.refresh(refresh_token=tokens.refresh_token)
    except WearableAuthError as exc:
        # Terminal until the user re-authorises — do not hammer it nightly.
        await _mark_needs_reauth(conn, exc.category)
        raise _Skip(exc.category) from exc

    async with scoped_session(household_id=conn.household_id, user_id=conn.member_id) as session:
        row = await session.get(WearableConnection, conn.id)
        if row is None:
            raise _Skip("connection_gone")
        # Wholesale replacement: providers rotate the refresh token, so merging would keep a
        # dead one around and lose the new one.
        row.tokens_enc = encode_tokens(box, renewed)
        row.token_expires_at = renewed.expires_at
        if renewed.scopes:
            row.scopes = list(renewed.scopes)
    return renewed.access_token


async def _upsert_day(
    session: AsyncSession,
    *,
    conn: _ConnRef,
    day: date,
    values: dict[str, int | None],
    now: datetime,
) -> None:
    row = await session.scalar(
        select(WearableDailyRow).where(
            WearableDailyRow.member_id == conn.member_id,
            WearableDailyRow.provider == conn.provider,
            WearableDailyRow.day == day,
        )
    )
    if row is None:
        session.add(
            WearableDailyRow(
                household_id=conn.household_id,
                member_id=conn.member_id,
                provider=conn.provider,
                day=day,
                fetched_at=now,
                **values,
            )
        )
        return
    for field, value in values.items():
        setattr(row, field, value)
    row.fetched_at = now


async def _ingest_one(
    conn: _ConnRef,
    *,
    cloud: WearableCloudPort,
    access_token: str,
    allowed: set[str],
    now: datetime,
) -> int:
    """Fetch and store the trailing window for one connection. Returns days written."""
    written = 0
    today = now.date()
    for offset in range(INGEST_WINDOW_DAYS):
        day = today - timedelta(days=offset)
        daily = await cloud.fetch_daily(access_token=access_token, day=day)
        if not daily.available:
            continue
        values = consented_values(daily, allowed)
        if all(value is None for value in values.values()):
            continue  # nothing consented, or nothing measured — store no empty row
        async with scoped_session(
            household_id=conn.household_id, user_id=conn.member_id
        ) as session:
            await _upsert_day(session, conn=conn, day=day, values=values, now=now)
        written += 1
    return written


async def ingest_all(
    *, cloud: WearableCloudPort, oauth: WearableOAuthPort, now: datetime
) -> IngestStats:
    """One full ingest run over every active connection (nightly worker cron)."""
    stats = IngestStats()
    box = get_secretbox()

    connections = await _load_connections()
    stats.connections = len(connections)

    for conn in connections:
        try:
            # Role first: a demotion must stop the outbound traffic too, not just the storage.
            role = await accounts_api.get_active_role(
                user_id=conn.member_id, household_id=conn.household_id
            )
            if role not in (Role.admin, Role.member):
                await _drop_connection(conn)
                stats.revoked += 1
                continue

            if box is None:
                # No server crypto key: pause rather than crash (ADR-0077).
                raise _Skip("crypto_unconfigured")
            if conn.tokens_enc is None:
                raise _Skip("no_tokens")

            access_token = await _refresh_if_due(conn, box=box, oauth=oauth, now=now)

            async with scoped_session(
                household_id=conn.household_id, user_id=conn.member_id
            ) as session:
                consents = await accounts_api.effective_consents(
                    session, subject_user_id=conn.member_id, types=ALL_CONSENT_TYPES
                )
            allowed = allowed_fields(consents)
            if not allowed:
                # Everything withdrawn between runs; 9-S5's PATCH already erased the values.
                raise _Skip("no_consent")

            written = await _ingest_one(
                conn, cloud=cloud, access_token=access_token, allowed=allowed, now=now
            )
            async with scoped_session(
                household_id=conn.household_id, user_id=conn.member_id
            ) as session:
                row = await session.get(WearableConnection, conn.id)
                if row is not None:
                    row.last_sync_at = now
                    row.last_error = None
            stats.ingested += 1
            stats.days_written += written
        except WearableAuthError as exc:
            await _mark_needs_reauth(conn, exc.category)
            stats.failed += 1
        except _Skip as exc:
            await _record_error(conn, exc.category)
            stats.skipped += 1
        except Exception:
            # Unexpected failure: isolate, log the class only, keep the loop alive.
            _log.exception("wearable_ingest_connection_failed", connection_id=str(conn.id))
            stats.failed += 1

    _log.info(
        "wearable_ingest_done",
        connections=stats.connections,
        ingested=stats.ingested,
        days_written=stats.days_written,
        skipped=stats.skipped,
        failed=stats.failed,
        revoked=stats.revoked,
    )
    return stats


async def reap_wearable_daily(session: AsyncSession, *, retention_days: int) -> int:
    """Hard-delete raw daily values older than ``retention_days`` (KONZEPT §11: Default 90 Tage).

    Runs as ``custode_maint`` across households (DELETE granted in migration 0070). Deliberately
    NOT part of the tombstone reaper: that one purges by ``deleted_at``, while these tables forbid
    tombstones entirely — the axis here is the age of the measured DAY.

    Aggregates survive by design: this only drops the raw per-day rows. ``wearable_connections``
    is untouched — a connection is not a measurement and stays until the member disconnects."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).date()
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(WearableDailyRow).where(WearableDailyRow.day < cutoff)),
    )
    await session.commit()
    return result.rowcount or 0
