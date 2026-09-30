"""Seed-demo DB test (Testcontainers Postgres 18): run the demo seeder and prove the
created admin can actually log in end-to-end, that the household is lived-in (members,
recipes, plan, shopping, tasks + ledger, notes, guide, events — all read back through the
modules' own services), and that re-running is idempotent. Repoints both the app engine
(self-scoped inserts) and the maint engine (login bootstrap) at a migrated container.
Skipped without Docker."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.tenancy.session import scoped_session
from app.modules.accounts.service import child_login, list_members, list_user_households, login
from app.modules.calendar.service import list_events
from app.modules.economy.service import balance, member_account
from app.modules.guides.service import list_guides
from app.modules.mealplanner.service import get_week
from app.modules.notes.service import list_notes
from app.modules.recipes.service import list_recipes
from app.modules.shopping.service import pull_shopping
from app.modules.tasks.service import list_instances
from app.scripts.seed_demo import (
    DEMO_CHILD_NAME,
    DEMO_CHILD_PIN,
    DEMO_CHILD_USERNAME,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    seed_demo_admin,
)
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def seed_db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint both the app and maint engines at the container for one test."""
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev_app = os.environ.get("CUSTODE_DATABASE_URL")
    prev_maint = os.environ.get("CUSTODE_DATABASE_URL_MAINT")
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = None
    engine_mod._sessionmaker = None
    engine_mod._maint_engine = None
    engine_mod._maint_sessionmaker = None
    try:
        yield
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = None
        engine_mod._sessionmaker = None
        engine_mod._maint_engine = None
        engine_mod._maint_sessionmaker = None
        for key, prev in (
            ("CUSTODE_DATABASE_URL", prev_app),
            ("CUSTODE_DATABASE_URL_MAINT", prev_maint),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        get_settings.cache_clear()


async def test_seed_creates_loginable_admin(seed_db: None) -> None:
    await seed_demo_admin()
    # The seeded credentials authenticate exactly like a normally-registered account.
    result = await login(email=DEMO_EMAIL, password=DEMO_PASSWORD, device_label="Test")
    assert result.refresh_token
    assert result.user_id is not None


async def test_seed_fills_a_lived_in_household(seed_db: None, redis_db: None) -> None:
    """Every seeded module reads back through its own service in an admin-scoped session — the
    same RLS path a request takes — so the seed cannot have bypassed a module's write path.
    (``redis_db``: the child login checks its PIN lockout counter in Redis.)"""
    await seed_demo_admin()
    admin = await login(email=DEMO_EMAIL, password=DEMO_PASSWORD)
    households = await list_user_households(user_id=admin.user_id)
    assert len(households) == 1
    household_id = households[0].household_id

    async with scoped_session(household_id=household_id, user_id=admin.user_id) as session:
        members = {m.display_name: m for m in await list_members(session)}
        assert {"Mira", "Jonas", "Lea", "Noah"} <= set(members)
        assert members["Mira"].role == "admin"
        assert members["Jonas"].role == "member"
        assert members["Noah"].role == "child"
        jonas, lea, noah = (members[n].user_id for n in ("Jonas", "Lea", "Noah"))

        recipes = await list_recipes(session)
        assert len(recipes) >= 4

        today = datetime.now(UTC).date()
        week_start = today - timedelta(days=today.weekday())
        _, slots, titles = await get_week(session, household_id=household_id, week_start=week_start)
        assert len(slots) == 7  # dinner every day this week
        assert any(s.recipe_id in titles for s in slots)
        assert any(s.free_text for s in slots)

        pulled = await pull_shopping(session, household_id=household_id, cursor=None)
        items = [c for c in pulled.changes if c.entity == "shopping_item"]
        assert len(items) >= 10
        assert any(c.fields.get("checked") for c in items)

        instances = await list_instances(session, status=None)
        assert len(instances) >= 6
        assert {i.status for i in instances} >= {"open", "done"}
        overdue = [i for i in instances if i.status == "open" and i.due_at is not None]
        assert any(i.due_at < datetime.now(UTC) for i in overdue)
        assert any(i.assigned_to is None for i in instances)

        # Completions were booked through the ledger (never a balance field): the doers hold
        # points, the never-completing admin holds none. The overdue "Bad putzen" decayed.
        for member_id in (jonas, lea, noah):
            assert await balance(session, account=member_account(member_id)) > 0
        assert await balance(session, account=member_account(admin.user_id)) == 0
        assert await balance(session, account=member_account(lea)) < 25

        notes = await list_notes(session)
        assert len(notes) == 2
        assert notes[0].pinned  # pinned notes sort first
        guides = await list_guides(session)
        assert len(guides) == 1
        assert guides[0].contact_id == jonas

        occurrences = await list_events(
            session,
            viewer_id=admin.user_id,
            frm=datetime.now(UTC),
            to=datetime.now(UTC) + timedelta(days=21),
        )
        assert {occ[0].title for occ in occurrences} >= {"Elternabend", "Fußballtraining Noah"}

    # Every account is loginable: the adults share the demo password, the child uses its PIN.
    assert (await login(email="jonas@custode.local", password=DEMO_PASSWORD)).refresh_token
    child, child_household, child_role = await child_login(
        household_id=household_id, username=DEMO_CHILD_USERNAME, pin=DEMO_CHILD_PIN
    )
    assert child.refresh_token
    assert (child_household, child_role.value) == (household_id, "child")
    assert members[DEMO_CHILD_NAME].user_id == child.user_id


async def test_seed_is_idempotent(seed_db: None) -> None:
    await seed_demo_admin()
    # A second run must not raise (e.g. duplicate-email conflict) and must leave login intact.
    await seed_demo_admin()
    result = await login(email=DEMO_EMAIL, password=DEMO_PASSWORD)
    assert result.refresh_token
    # ... and must not have doubled the household's content.
    households = await list_user_households(user_id=result.user_id)
    assert len(households) == 1
    async with scoped_session(
        household_id=households[0].household_id, user_id=result.user_id
    ) as session:
        assert len(await list_members(session)) == 4
        assert len(await list_notes(session)) == 2
