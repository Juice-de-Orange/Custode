"""``demo-reset`` (``app/scripts/demo_reset.py``) on a real, migrated Postgres + Redis.

What the public demo depends on: the first run seeds the household; every later run puts the
database back to **exactly** that state — same tables, same row counts, the migrations' reference
data intact — however visitors changed it, in well under a minute. And the command refuses
whenever running it would be wrong: demo mode off, accounts but no base copy, a base copy from an
older schema.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.kernel.db.engine as engine_mod
from app.kernel.tenancy.session import scoped_session
from app.modules.accounts.service import list_user_households, login
from app.modules.notes.schemas import NoteCreate
from app.modules.notes.service import create_note, list_notes
from app.scripts.demo_reset import BASE_SCHEMA, reset_demo, table_counts
from app.scripts.seed_demo import CONTENT, DEMO_EMAIL, DEMO_PASSWORD
from app.settings import get_settings
from conftest import PgDatabase

_ENV = (
    "CUSTODE_DATABASE_URL",
    "CUSTODE_DATABASE_URL_MAINT",
    "CUSTODE_DATABASE_URL_ADMIN",
    "CUSTODE_DEMO_MODE",
)


def _reset_engines() -> None:
    engine_mod._engine = None
    engine_mod._sessionmaker = None
    engine_mod._maint_engine = None
    engine_mod._maint_sessionmaker = None


@pytest.fixture
async def demo_db(pg: PgDatabase, redis_db: None) -> AsyncIterator[str]:
    """Point app, maint and admin URLs at this module's database, demo mode on. Yields the admin
    URL. The module database is shared by the tests below, which run in order."""
    previous = {key: os.environ.get(key) for key in _ENV}
    admin = pg.dsn(pg.username, pg.password)
    os.environ["CUSTODE_DATABASE_URL"] = pg.dsn("custode_app", "app")
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = pg.dsn("custode_maint", "maint")
    os.environ["CUSTODE_DATABASE_URL_ADMIN"] = admin
    os.environ["CUSTODE_DEMO_MODE"] = "on"
    get_settings.cache_clear()
    _reset_engines()
    try:
        yield admin
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        _reset_engines()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


async def _counts(admin_url: str) -> dict[str, int]:
    engine = create_async_engine(admin_url)
    try:
        async with engine.connect() as conn:
            return await table_counts(conn)
    finally:
        await engine.dispose()


async def _scribble(n_notes: int) -> None:
    """What visitors do: add content, as the demo admin, through the normal service path."""
    admin = await login(email=DEMO_EMAIL, password=DEMO_PASSWORD)
    household_id = (await list_user_households(user_id=admin.user_id))[0].household_id
    async with scoped_session(household_id=household_id, user_id=admin.user_id) as session:
        for i in range(n_notes):
            await create_note(
                session,
                household_id=household_id,
                author_id=admin.user_id,
                data=NoteCreate(title=f"visitor {i}", body_md="x" * 100),
            )


async def test_refuses_without_demo_mode(demo_db: str) -> None:
    os.environ["CUSTODE_DEMO_MODE"] = "off"
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="CUSTODE_DEMO_MODE"):
        await reset_demo()


async def test_first_run_seeds_then_every_run_restores_exactly(demo_db: str) -> None:
    before = await _counts(demo_db)
    reference = before.get("ingredients", 0)
    assert reference > 0  # the migrations' reference data, which a naive wipe would lose
    assert "users" not in before

    first = await reset_demo("en")
    assert first.action == "initialised"
    seeded = await _counts(demo_db)
    assert seeded == first.rows
    assert seeded["users"] == 4  # admin, two adults, the child
    assert seeded["ingredients"] == reference

    # Visitors scribble; the counts drift.
    await _scribble(3)
    drifted = await _counts(demo_db)
    assert drifted != seeded

    second = await reset_demo("en")
    assert second.action == "restored"
    assert second.seconds < 60
    assert await _counts(demo_db) == seeded  # every table, exactly

    # The household is the English one, and the visitors' notes are gone.
    admin = await login(email=DEMO_EMAIL, password=DEMO_PASSWORD)
    households = await list_user_households(user_id=admin.user_id)
    assert [h.name for h in households] == [CONTENT["en"].household]
    async with scoped_session(
        household_id=households[0].household_id, user_id=admin.user_id
    ) as session:
        titles = {n.title for n in await list_notes(session)}
    assert titles == {title for title, _, _ in CONTENT["en"].notes}


async def test_refuses_a_base_copy_from_another_schema_revision(demo_db: str) -> None:
    engine = create_async_engine(demo_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"COMMENT ON SCHEMA {BASE_SCHEMA} IS 'older'"))
        with pytest.raises(SystemExit, match="revision older"):
            await reset_demo("en")
    finally:
        await engine.dispose()


async def test_refuses_accounts_without_a_base_copy(demo_db: str) -> None:
    engine = create_async_engine(demo_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {BASE_SCHEMA} CASCADE"))
        with pytest.raises(SystemExit, match="no base copy"):
            await reset_demo("en")
    finally:
        await engine.dispose()


def test_both_seed_languages_have_the_same_shape() -> None:
    """The reset compares counts; a language with one recipe more would be a different demo."""
    de, en = CONTENT["de"], CONTENT["en"]
    assert len(de.recipes) == len(en.recipes)
    assert [len(r.ingredients) for r in de.recipes] == [len(r.ingredients) for r in en.recipes]
    assert len(de.shopping) == len(en.shopping)
    assert [t[0] for t in de.templates] == [t[0] for t in en.templates]
    assert [r[0] for r in de.rooms] == [r[0] for r in en.rooms]
    assert len(de.notes) == len(en.notes)


async def test_seed_refuses_outside_dev_without_demo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts.seed_demo import seed_demo_admin

    monkeypatch.setenv("CUSTODE_ENV", "production")
    monkeypatch.setenv("CUSTODE_DEMO_MODE", "off")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="known password"):
            await seed_demo_admin()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
