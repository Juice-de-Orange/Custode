"""Integration tests for the wearable ingest + retention run (P9-S6, Testcontainers PG 18).

The unit tests cover the mapping; this file covers what only a real database and a real RLS
policy can show: that the run writes under the OWNER's scope (the maint role is denied by
design), that a role demotion erases the record, that a rejected refresh parks the connection,
and that retention drops raw values by the age of the measured DAY.

Skipped without Docker.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.crypto import SecretBox, generate_key
from app.kernel.ports.wearable import (
    UNKNOWN_WEARABLE,
    WearableAuthError,
    WearableDaily,
    WearableTokens,
)
from app.modules.wearables.sync import ingest_all, reap_wearable_daily
from app.modules.wearables.tokens import encode_tokens
from app.settings import get_settings
from conftest import PgDatabase

NOW = datetime(2026, 7, 27, 4, 20, tzinfo=UTC)
_ALL_TYPES = ("wearable_sleep", "wearable_readiness", "wearable_activity", "wearable_heartrate")


# ------------------------------------------------------------------ fakes


class FakeCloud:
    """Records every fetch so a test can assert that no outbound call happened at all."""

    def __init__(self, daily: WearableDaily | None = None) -> None:
        self.daily = daily or WearableDaily(
            available=True,
            sleep_score=80,
            sleep_minutes=420,
            readiness=70,
            steps=9000,
            active_kcal=400,
            rhr=55,
        )
        self.calls: list[tuple[str, object]] = []
        self.raise_auth: str | None = None

    async def fetch_daily(self, *, access_token: str, day: object) -> WearableDaily:
        self.calls.append((access_token, day))
        if self.raise_auth:
            raise WearableAuthError(self.raise_auth)
        return self.daily


class FakeOAuth:
    def __init__(self) -> None:
        self.refreshed = 0
        self.fail_with: str | None = None
        self.new_tokens = WearableTokens(
            access_token="fresh-access", refresh_token="fresh-refresh", scopes=["daily"]
        )

    def authorize_url(self, *, state: str, scopes: list[str], redirect_uri: str) -> str:
        raise AssertionError("ingest must never build an authorize URL")

    async def exchange_code(self, *, code: str, redirect_uri: str) -> WearableTokens:
        raise AssertionError("ingest must never exchange a code")

    async def refresh(self, *, refresh_token: str) -> WearableTokens:
        self.refreshed += 1
        if self.fail_with:
            raise WearableAuthError(self.fail_with)
        return self.new_tokens


# ------------------------------------------------------------------ infrastructure


@pytest.fixture
async def db(pg: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = {k: os.environ.get(k) for k in ("CUSTODE_DATABASE_URL", "CUSTODE_DATABASE_URL_MAINT")}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    key = generate_key()
    monkeypatch.setenv("CUSTODE_CRYPTO_KEY", key)
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    try:
        yield key
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
        for name, value in prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def clean_tables(pg: PgDatabase) -> AsyncIterator[None]:
    """Wipe the tables this module seeds before every test.

    ``ingest_all`` enumerates connections GLOBALLY (that is its job), so leftovers from a previous
    test would silently inflate every ``IngestStats`` assertion. The container is module-scoped
    for speed, so isolation has to come from here."""
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute(
            "TRUNCATE wearable_daily, wearable_connections, consents, memberships, "
            "households, users CASCADE;"
        )
    finally:
        await conn.close()
    yield


# ------------------------------------------------------------------ seeding helpers


async def _conn(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


async def _seed_member(
    pg: PgDatabase,
    *,
    key: str,
    role: str = "member",
    expires_at: datetime | None = None,
    consents: tuple[str, ...] = _ALL_TYPES,
    refresh_token: str | None = "stored-refresh",  # noqa: S107 — Test-Fixture
) -> tuple[uuid.UUID, uuid.UUID]:
    """One household + one member with an active connection and the given consents."""
    household_id, member_id = uuid.uuid4(), uuid.uuid4()
    tokens_enc = encode_tokens(
        SecretBox(key),
        WearableTokens(access_token="stored-access", refresh_token=refresh_token),
    )
    conn = await _conn(pg)
    try:
        await conn.execute(
            "INSERT INTO households (id, name) VALUES ($1, 'Familie');", household_id
        )
        await conn.execute(
            "INSERT INTO users (id, display_name) VALUES ($1, 'Mitglied');", member_id
        )
        await conn.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,$3);",
            household_id,
            member_id,
            role,
        )
        await conn.execute(
            "INSERT INTO wearable_connections "
            "(household_id, member_id, provider, tokens_enc, token_expires_at, status) "
            "VALUES ($1,$2,'oura',$3,$4,'active');",
            household_id,
            member_id,
            tokens_enc,
            expires_at,
        )
        for consent_type in consents:
            await conn.execute(
                "INSERT INTO consents "
                "(household_id, subject_user_id, type, action, granted_by) "
                "VALUES ($1,$2,$3,'grant',$2);",
                household_id,
                member_id,
                consent_type,
            )
    finally:
        await conn.close()
    return household_id, member_id


async def _fetchval(pg: PgDatabase, query: str, *args: object) -> object:
    conn = await _conn(pg)
    try:
        return await conn.fetchval(query, *args)
    finally:
        await conn.close()


# ------------------------------------------------------------------ happy path


async def test_ingest_writes_the_trailing_window_under_the_owner_scope(
    pg: PgDatabase, db: str
) -> None:
    """The maint role has no write grant on these tables (member-scoped RLS) — that the rows
    appear at all proves the run switched to the owner's scope."""
    household_id, member_id = await _seed_member(pg, key=db)
    cloud = FakeCloud()

    stats = await ingest_all(cloud=cloud, oauth=FakeOAuth(), now=NOW)

    assert stats.ingested == 1
    assert stats.days_written == 3  # INGEST_WINDOW_DAYS
    assert len(cloud.calls) == 3
    rows = await _fetchval(
        pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id
    )
    assert rows == 3
    stored = await _fetchval(
        pg,
        "SELECT sleep_score FROM wearable_daily WHERE member_id = $1 AND day = $2;",
        member_id,
        NOW.date(),
    )
    assert stored == 80
    assert (
        await _fetchval(
            pg, "SELECT last_error FROM wearable_connections WHERE member_id = $1;", member_id
        )
        is None
    )
    assert household_id  # seeded household is the scope the rows were written under


async def test_rerun_updates_the_same_day_instead_of_duplicating(pg: PgDatabase, db: str) -> None:
    """Providers correct a night's values afterwards — that is why the window is re-fetched."""
    _, member_id = await _seed_member(pg, key=db)
    await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)
    corrected = FakeCloud(WearableDaily(available=True, sleep_score=91))
    await ingest_all(cloud=corrected, oauth=FakeOAuth(), now=NOW)

    assert (
        await _fetchval(pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id)
        == 3
    )
    assert (
        await _fetchval(
            pg,
            "SELECT sleep_score FROM wearable_daily WHERE member_id = $1 AND day = $2;",
            member_id,
            NOW.date(),
        )
        == 91
    )


async def test_unavailable_days_store_no_row(pg: PgDatabase, db: str) -> None:
    _, member_id = await _seed_member(pg, key=db)
    stats = await ingest_all(cloud=FakeCloud(UNKNOWN_WEARABLE), oauth=FakeOAuth(), now=NOW)
    assert stats.days_written == 0
    assert (
        await _fetchval(pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id)
        == 0
    )


# ------------------------------------------------------------------ consent enforcement


async def test_only_consented_types_are_stored(pg: PgDatabase, db: str) -> None:
    """The `daily` provider scope covers sleep, readiness AND activity — consenting to sleep
    alone must still store nothing else."""
    _, member_id = await _seed_member(pg, key=db, consents=("wearable_sleep",))
    await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)

    conn = await _conn(pg)
    try:
        row = await conn.fetchrow(
            "SELECT sleep_score, readiness, steps, rhr FROM wearable_daily "
            "WHERE member_id = $1 AND day = $2;",
            member_id,
            NOW.date(),
        )
    finally:
        await conn.close()
    assert row["sleep_score"] == 80
    assert row["readiness"] is None
    assert row["steps"] is None
    assert row["rhr"] is None


async def test_connection_without_any_consent_is_skipped(pg: PgDatabase, db: str) -> None:
    _, member_id = await _seed_member(pg, key=db, consents=())
    cloud = FakeCloud()
    stats = await ingest_all(cloud=cloud, oauth=FakeOAuth(), now=NOW)

    assert stats.skipped == 1
    assert cloud.calls == []  # no outbound request without a legal basis
    assert (
        await _fetchval(
            pg, "SELECT last_error FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == "no_consent"
    )


async def test_revoked_consent_nulls_the_value_on_the_next_run(pg: PgDatabase, db: str) -> None:
    """A type withdrawn between runs must lose its stored value — not keep last night's."""
    household_id, member_id = await _seed_member(pg, key=db)
    await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)

    conn = await _conn(pg)
    try:
        await conn.execute(
            "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
            "VALUES ($1,$2,'wearable_activity','revoke',$2);",
            household_id,
            member_id,
        )
    finally:
        await conn.close()

    await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)
    assert (
        await _fetchval(
            pg,
            "SELECT steps FROM wearable_daily WHERE member_id = $1 AND day = $2;",
            member_id,
            NOW.date(),
        )
        is None
    )


# ------------------------------------------------------------------ role follow-up


@pytest.mark.parametrize("role", ["child", "guest"])
async def test_demoted_member_loses_connection_and_data(pg: PgDatabase, db: str, role: str) -> None:
    """Kinder haben keine Wearables (Root-CLAUDE.md). A demotion after the fact must erase the
    record — and stop the traffic, so no fetch may happen at all."""
    household_id, member_id = await _seed_member(pg, key=db)
    await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)
    assert (
        await _fetchval(pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id)
        == 3
    )

    conn = await _conn(pg)
    try:
        await conn.execute("UPDATE memberships SET role = $2 WHERE user_id = $1;", member_id, role)
    finally:
        await conn.close()

    cloud = FakeCloud()
    stats = await ingest_all(cloud=cloud, oauth=FakeOAuth(), now=NOW)

    assert stats.revoked == 1
    assert cloud.calls == []  # checked BEFORE any outbound request
    assert (
        await _fetchval(
            pg, "SELECT count(*) FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == 0
    )
    assert (
        await _fetchval(pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id)
        == 0
    )
    assert household_id


# ------------------------------------------------------------------ token refresh


async def test_expiring_token_is_refreshed_and_stored_wholesale(pg: PgDatabase, db: str) -> None:
    """Providers rotate refresh tokens — the answer replaces the stored value entirely."""
    _, member_id = await _seed_member(pg, key=db, expires_at=NOW + timedelta(minutes=5))
    cloud, oauth = FakeCloud(), FakeOAuth()

    await ingest_all(cloud=cloud, oauth=oauth, now=NOW)

    assert oauth.refreshed == 1
    assert cloud.calls[0][0] == "fresh-access"  # the run used the NEW token
    stored = await _fetchval(
        pg, "SELECT tokens_enc FROM wearable_connections WHERE member_id = $1;", member_id
    )
    from app.modules.wearables.tokens import decode_tokens

    restored = decode_tokens(SecretBox(db), str(stored))
    assert restored.access_token == "fresh-access"
    assert restored.refresh_token == "fresh-refresh"  # rotated, old one gone


async def test_valid_token_is_not_refreshed(pg: PgDatabase, db: str) -> None:
    _, _member = await _seed_member(pg, key=db, expires_at=NOW + timedelta(days=1))
    oauth = FakeOAuth()
    await ingest_all(cloud=FakeCloud(), oauth=oauth, now=NOW)
    assert oauth.refreshed == 0


async def test_rejected_refresh_parks_the_connection(pg: PgDatabase, db: str) -> None:
    """Terminal until the user re-authorises — the next night must not hammer it again."""
    _, member_id = await _seed_member(pg, key=db, expires_at=NOW - timedelta(minutes=1))
    oauth = FakeOAuth()
    oauth.fail_with = "refresh_failed"
    cloud = FakeCloud()

    stats = await ingest_all(cloud=cloud, oauth=oauth, now=NOW)

    assert stats.skipped == 1
    assert cloud.calls == []
    conn = await _conn(pg)
    try:
        row = await conn.fetchrow(
            "SELECT status, last_error FROM wearable_connections WHERE member_id = $1;", member_id
        )
    finally:
        await conn.close()
    assert row["status"] == "needs_reauth"
    assert row["last_error"] == "refresh_failed"

    # Parked connections are not enumerated again.
    second = await ingest_all(cloud=cloud, oauth=oauth, now=NOW)
    assert second.connections == 0
    assert oauth.refreshed == 1


async def test_expired_token_without_a_refresh_token_is_skipped(pg: PgDatabase, db: str) -> None:
    _, member_id = await _seed_member(
        pg, key=db, expires_at=NOW - timedelta(hours=1), refresh_token=None
    )
    stats = await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)
    assert stats.skipped == 1
    assert (
        await _fetchval(
            pg, "SELECT last_error FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == "no_refresh_token"
    )


async def test_rejected_access_token_flags_reauth(pg: PgDatabase, db: str) -> None:
    _, member_id = await _seed_member(pg, key=db)
    cloud = FakeCloud()
    cloud.raise_auth = "token_rejected"

    stats = await ingest_all(cloud=cloud, oauth=FakeOAuth(), now=NOW)

    assert stats.failed == 1
    assert (
        await _fetchval(
            pg, "SELECT status FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == "needs_reauth"
    )


async def test_undecryptable_tokens_pause_the_connection(pg: PgDatabase, db: str) -> None:
    """A rotated crypto key must not crash the run — it parks the affected connection."""
    _, member_id = await _seed_member(pg, key=generate_key())  # encrypted with a FOREIGN key
    stats = await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)
    assert stats.skipped == 1
    assert (
        await _fetchval(
            pg, "SELECT last_error FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == "tokens_undecryptable"
    )


async def test_one_broken_connection_does_not_stop_the_others(pg: PgDatabase, db: str) -> None:
    """Failure isolation: a bad connection records its category, the loop continues."""
    await _seed_member(pg, key=generate_key())  # undecryptable
    _, healthy = await _seed_member(pg, key=db)

    stats = await ingest_all(cloud=FakeCloud(), oauth=FakeOAuth(), now=NOW)

    assert stats.skipped == 1
    assert stats.ingested == 1
    assert (
        await _fetchval(pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", healthy)
        == 3
    )


# ------------------------------------------------------------------ retention


async def test_retention_drops_values_by_the_age_of_the_measured_day(
    pg: PgDatabase, db: str
) -> None:
    household_id, member_id = await _seed_member(pg, key=db)
    conn = await _conn(pg)
    try:
        for offset in (10, 89, 91, 400):
            await conn.execute(
                "INSERT INTO wearable_daily (household_id, member_id, provider, day, sleep_score) "
                "VALUES ($1,$2,'oura', (CURRENT_DATE - $3::int), 70);",
                household_id,
                member_id,
                offset,
            )
    finally:
        await conn.close()

    from app.kernel.db.engine import get_maint_sessionmaker

    factory = get_maint_sessionmaker()
    async with factory() as session:
        removed = await reap_wearable_daily(session, retention_days=90)

    assert removed == 2  # the 91- and 400-day-old rows
    remaining = await _fetchval(
        pg, "SELECT count(*) FROM wearable_daily WHERE member_id = $1;", member_id
    )
    assert remaining == 2
    # The connection itself is not a measurement and survives.
    assert (
        await _fetchval(
            pg, "SELECT count(*) FROM wearable_connections WHERE member_id = $1;", member_id
        )
        == 1
    )
