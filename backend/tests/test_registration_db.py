"""Registration DB tests (Testcontainers Postgres 18). Repoints the global engine
at a migrated container as ``custode_app`` and exercises ``register_user``'s
self-scoped insert (users WITH CHECK id = app.user_id) and the duplicate-email
conflict. Skipped without Docker. This is the reusable pattern for service tests
that go through ``scoped_session``."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.http.problem import ProblemException
from app.modules.accounts.service import register_user
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret


def _hibp_clean() -> httpx.AsyncClient:
    # No suffix ever matches -> pwned_count == 0 (clean), no real network call.
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, text="AAAAA" + "0" * 30 + ":1")
        )
    )


@pytest.fixture
async def app_db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint the global engine at the container as custode_app for one test."""
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = os.environ.get("CUSTODE_DATABASE_URL")
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = None
    engine_mod._sessionmaker = None
    try:
        yield
    finally:
        if engine_mod._engine is not None:
            await engine_mod._engine.dispose()
        engine_mod._engine = None
        engine_mod._sessionmaker = None
        if prev is None:
            os.environ.pop("CUSTODE_DATABASE_URL", None)
        else:
            os.environ["CUSTODE_DATABASE_URL"] = prev
        get_settings.cache_clear()


async def test_register_creates_user(app_db: None) -> None:
    async with _hibp_clean() as client:
        uid = await register_user(
            email="Neu@Example.DE",
            password=_PASSWORD,
            display_name="Neu",
            pwned_client=client,
        )
    assert isinstance(uid, uuid.UUID)


async def test_register_duplicate_email_conflicts(app_db: None) -> None:
    async with _hibp_clean() as client:
        await register_user(
            email="dup@example.de", password=_PASSWORD, display_name="One", pwned_client=client
        )
        with pytest.raises(ProblemException) as ei:
            await register_user(
                email="dup@example.de", password=_PASSWORD, display_name="Two", pwned_client=client
            )
    assert ei.value.slug == "email_taken"
