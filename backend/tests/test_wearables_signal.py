"""Tests for the wearables -> scheduling seam (P9-S7, Synergie S-14).

The pure half (``evaluate``) needs no infrastructure. The query half gets a real database,
because the claim that matters — a member cannot pull anybody else's signal — is an RLS claim
and a mock would prove nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest

from app.modules.wearables.signal import (
    LOW_SCORE_THRESHOLD,
    MAX_READING_AGE_DAYS,
    evaluate,
)
from conftest import PgDatabase

TODAY = date(2026, 7, 27)


# ------------------------------------------------------------------ pure decision rule


def test_low_scores_mean_low_recovery() -> None:
    signal = evaluate(readiness=40, sleep_score=90, day=TODAY, today=TODAY)
    assert signal.available is True
    assert signal.low_recovery is True
    assert signal.as_of == TODAY


def test_either_score_alone_is_enough() -> None:
    """Requiring BOTH would silence the signal for anyone who consented to only one data type."""
    assert evaluate(readiness=40, sleep_score=None, day=TODAY, today=TODAY).low_recovery is True
    assert evaluate(readiness=None, sleep_score=40, day=TODAY, today=TODAY).low_recovery is True


def test_good_scores_are_available_but_not_low() -> None:
    signal = evaluate(readiness=85, sleep_score=80, day=TODAY, today=TODAY)
    assert (signal.available, signal.low_recovery) == (True, False)


def test_threshold_boundary_is_not_low() -> None:
    at = evaluate(readiness=LOW_SCORE_THRESHOLD, sleep_score=None, day=TODAY, today=TODAY)
    below = evaluate(readiness=LOW_SCORE_THRESHOLD - 1, sleep_score=None, day=TODAY, today=TODAY)
    assert at.low_recovery is False
    assert below.low_recovery is True


def test_yesterdays_reading_still_counts() -> None:
    yesterday = TODAY - timedelta(days=MAX_READING_AGE_DAYS)
    assert evaluate(readiness=30, sleep_score=None, day=yesterday, today=TODAY).available is True


def test_a_stale_reading_says_nothing() -> None:
    """A value from days ago describes a different day; treating it as current would be worse
    than having no signal at all."""
    old = TODAY - timedelta(days=MAX_READING_AGE_DAYS + 1)
    signal = evaluate(readiness=10, sleep_score=10, day=old, today=TODAY)
    assert (signal.available, signal.low_recovery) == (False, False)


def test_a_row_without_any_score_says_nothing() -> None:
    """Consent for activity only: steps are stored, the scores are NULL — no recovery statement."""
    signal = evaluate(readiness=None, sleep_score=None, day=TODAY, today=TODAY)
    assert signal.available is False


# ------------------------------------------------------------------ the RLS claim

import asyncpg

import app.kernel.db.engine as engine_mod
from app.kernel.tenancy.session import scoped_session
from app.modules.wearables import api as wearables_api
from app.settings import get_settings


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    import os

    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = {k: os.environ.get(k) for k in ("CUSTODE_DATABASE_URL", "CUSTODE_DATABASE_URL_MAINT")}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    try:
        yield
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


async def _seed_reading(
    pg: PgDatabase, *, household: uuid.UUID, member: uuid.UUID, readiness: int
) -> None:
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute(
            "INSERT INTO wearable_daily (household_id, member_id, provider, day, readiness) "
            "VALUES ($1,$2,'oura', CURRENT_DATE, $3) ON CONFLICT DO NOTHING;",
            household,
            member,
            readiness,
        )
    finally:
        await conn.close()


async def test_member_reads_their_own_signal(pg: PgDatabase, db: None) -> None:
    household, alice = uuid.uuid4(), uuid.uuid4()
    await _seed_reading(pg, household=household, member=alice, readiness=35)

    async with scoped_session(household_id=household, user_id=alice) as session:
        signal = await wearables_api.recovery_signal(session, member_id=alice, today=date.today())
    assert (signal.available, signal.low_recovery) == (True, True)


async def test_a_co_member_cannot_pull_a_foreign_signal(pg: PgDatabase, db: None) -> None:
    """The seam takes a member_id, so a careless caller could pass somebody else's. The
    member-scoped RLS (migration 0069) makes that return nothing — the guarantee is enforced by
    the database, not by the caller remembering (N-2, ADR-0081)."""
    household, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed_reading(pg, household=household, member=alice, readiness=35)

    async with scoped_session(household_id=household, user_id=bob) as session:
        signal = await wearables_api.recovery_signal(session, member_id=alice, today=date.today())
    assert signal.available is False
    assert signal.low_recovery is False


async def test_no_reading_is_the_base_path(pg: PgDatabase, db: None) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    async with scoped_session(household_id=household, user_id=member) as session:
        signal = await wearables_api.recovery_signal(session, member_id=member, today=date.today())
    assert signal.available is False
