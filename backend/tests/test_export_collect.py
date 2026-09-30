"""The export against a real database (Testcontainers PG 18) — Art. 15 / Art. 20.

The claim under test is the one the module docstring makes: **tenancy comes from RLS, not from a
WHERE clause**. Nothing in ``collect_export`` filters by ``household_id``, so if RLS did not hold,
a household export would hand a stranger's data to the caller in a downloadable file.

The decisive case is not household-vs-household (every table has that test already) but the
Art.-9 one: an **admin** exporting their own household must not receive a co-member's wearable
rows. That is exactly what member-scoped RLS promises (ADR-0081) and exactly what a bulk
"SELECT * FROM every table" would break if the promise were only a convention in service code.

Skipped without Docker.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.export_policy import POLICY
from app.kernel.db import engine as engine_mod
from app.kernel.export import REDACTED, ExportScope, ExportTooLarge, collect_export
from app.kernel.tenancy.session import scoped_session
from app.settings import get_settings
from conftest import PgDatabase

# A value that must never appear in an export, however the row is serialised.
SECRET_TOKENS = "v1:ZmFrZS1vdXJhLXRva2Vu-not-for-export"


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = os.environ.get("CUSTODE_DATABASE_URL")
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    try:
        yield
    finally:
        if engine_mod._engine is not None:
            await engine_mod._engine.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        if prev is None:
            os.environ.pop("CUSTODE_DATABASE_URL", None)
        else:
            os.environ["CUSTODE_DATABASE_URL"] = prev
        get_settings.cache_clear()


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


@pytest.fixture
async def world(pg: PgDatabase, db: None) -> dict[str, uuid.UUID]:
    """Two households; in the first an admin and a member, each with wearable data.

    Seeded as the superuser so RLS plays no part in *writing* — the test is about reading.
    """
    ids = {
        "h_a": uuid.uuid4(),
        "h_b": uuid.uuid4(),
        "admin": uuid.uuid4(),
        "member": uuid.uuid4(),
        "outsider": uuid.uuid4(),
    }
    conn = await _su(pg)
    try:
        await conn.execute("TRUNCATE households, users, memberships, notes CASCADE;")
        await conn.execute("TRUNCATE wearable_connections, wearable_daily, recipes CASCADE;")
        for key, name in (("h_a", "Haus A"), ("h_b", "Haus B")):
            await conn.execute("INSERT INTO households (id, name) VALUES ($1,$2);", ids[key], name)
        for key, email in (
            ("admin", "admin@example.org"),
            ("member", "member@example.org"),
            ("outsider", "outsider@example.org"),
        ):
            await conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES ($1,$2,$3);",
                ids[key],
                email,
                key,
            )
        for key, role in (("admin", "admin"), ("member", "member")):
            await conn.execute(
                "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,$3);",
                ids["h_a"],
                ids[key],
                role,
            )
        await conn.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,'admin');",
            ids["h_b"],
            ids["outsider"],
        )
        # Wearables: one row per member. The member's token is the value that must never escape.
        for key, token in (("admin", "v1:admin-token"), ("member", SECRET_TOKENS)):
            await conn.execute(
                "INSERT INTO wearable_connections (household_id, member_id, provider, tokens_enc) "
                "VALUES ($1,$2,'oura',$3);",
                ids["h_a"],
                ids[key],
                token,
            )
            await conn.execute(
                "INSERT INTO wearable_daily "
                "(household_id, member_id, provider, day, sleep_score) "
                "VALUES ($1,$2,'oura',CURRENT_DATE,71);",
                ids["h_a"],
                ids[key],
            )
        # A shared fact row (no personal attribution) and one authored by the member.
        await conn.execute(
            "INSERT INTO recipes (household_id, title) VALUES ($1,'Geteiltes Rezept');",
            ids["h_a"],
        )
        await conn.execute(
            "INSERT INTO notes (household_id, author_id, title, body_md) "
            "VALUES ($1,$2,'Notiz des Mitglieds','...');",
            ids["h_a"],
            ids["member"],
        )
        # The other household's data — must never appear.
        await conn.execute(
            "INSERT INTO recipes (household_id, title) VALUES ($1,'Fremdes Rezept');",
            ids["h_b"],
        )
    finally:
        await conn.close()
    return ids


# --- the Art. 9 case ---------------------------------------------------------------------------


async def test_household_export_withholds_a_co_members_health_data(
    world: dict[str, uuid.UUID],
) -> None:
    """An admin exporting the household gets their own wearable rows and nobody else's.

    Not a service-layer filter — the policy predicate carries ``member_id`` (ADR-0081), so the
    bulk read simply cannot see the other row. Remove ``member_id`` from migration 0069 and this
    test goes red while every household-vs-household test stays green.
    """
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )

    members = {row["member_id"] for row in result.sections["wearable_connections"]}
    assert members == {str(world["admin"])}
    assert {row["member_id"] for row in result.sections["wearable_daily"]} == {str(world["admin"])}


async def test_the_co_members_token_appears_nowhere_in_the_payload(
    world: dict[str, uuid.UUID],
) -> None:
    """Belt and braces: serialise everything and search the text. A future column that copies the
    token elsewhere would be caught here even if the row-level assertion above still passed."""
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    assert SECRET_TOKENS not in json.dumps(result.sections, ensure_ascii=False)


# --- tenancy -----------------------------------------------------------------------------------


async def test_export_never_crosses_the_household(world: dict[str, uuid.UUID]) -> None:
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    titles = {row["title"] for row in result.sections["recipes"]}
    assert titles == {"Geteiltes Rezept"}
    assert all(row["id"] != str(world["h_b"]) for row in result.sections["households"])


# --- redaction ---------------------------------------------------------------------------------


async def test_own_credentials_are_redacted_not_omitted(world: dict[str, uuid.UUID]) -> None:
    """The subject sees THAT a token exists and that we kept it back — the key is present, the
    value is the marker. Omitting the key would imply no token exists."""
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    rows = result.sections["wearable_connections"]
    assert rows and all("tokens_enc" in row for row in rows)
    assert {row["tokens_enc"] for row in rows} == {REDACTED}


async def test_password_hashes_never_leave(world: dict[str, uuid.UUID]) -> None:
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    for row in result.sections["users"]:
        assert row["password_hash"] == REDACTED
        assert row["totp_secret"] == REDACTED


# --- personal scope ----------------------------------------------------------------------------


async def test_personal_export_returns_only_the_subjects_rows(
    world: dict[str, uuid.UUID],
) -> None:
    async with scoped_session(household_id=world["h_a"], user_id=world["member"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.PERSONAL, subject_id=world["member"]
        )
    assert [row["title"] for row in result.sections["notes"]] == ["Notiz des Mitglieds"]
    assert {row["member_id"] for row in result.sections["wearable_daily"]} == {str(world["member"])}


async def test_personal_export_skips_shared_tables_and_says_so(
    world: dict[str, uuid.UUID],
) -> None:
    """A shared recipe is not "data concerning" one member. The export must not silently drop it —
    the manifest names the table and the reason."""
    async with scoped_session(household_id=world["h_a"], user_id=world["member"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.PERSONAL, subject_id=world["member"]
        )
    assert "recipes" not in result.sections
    assert "recipes" in result.skipped
    assert "Haushalts-Export" in result.skipped["recipes"]


@pytest.mark.parametrize("scope", [ExportScope.PERSONAL, ExportScope.HOUSEHOLD])
async def test_export_demands_the_calling_person(scope: ExportScope) -> None:
    """Both scopes need it: the personal one to filter everything, the household one because the
    ``subject_scoped`` tables would otherwise widen to the whole household."""
    with pytest.raises(ValueError, match="person running it"):
        await collect_export(None, policy=POLICY, scope=scope)  # type: ignore[arg-type]


# --- shape -------------------------------------------------------------------------------------


async def test_result_is_json_serialisable(world: dict[str, uuid.UUID]) -> None:
    """uuid/datetime/Decimal must already be converted — a serialisation error at response time
    would fail the download after the work was done."""
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    payload = json.dumps({"sections": result.sections, "skipped": result.skipped})
    assert json.loads(payload)["sections"]["recipes"]


async def test_every_allowed_table_is_actually_readable(world: dict[str, uuid.UUID]) -> None:
    """The policy claims 42 tables are exportable. If one of them revoked SELECT from
    ``custode_app`` (like ``audit_log`` did), the export would blow up at request time for real
    users — find it here instead."""
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        result = await collect_export(
            session, policy=POLICY, scope=ExportScope.HOUSEHOLD, subject_id=world["admin"]
        )
    assert set(result.sections) == {spec.name for spec in POLICY.tables}


async def test_the_row_limit_bites_while_collecting(world: dict[str, uuid.UUID]) -> None:
    """Die Grenze muss greifen, BEVOR der Speicher ausgegeben ist. Eine Pruefung am fertigen
    Archiv waere Theater: dann lagen Zeilen, JSON und ZIP bereits gleichzeitig im RAM, und die
    Absage haette mehr gekostet als die Antwort."""
    async with scoped_session(household_id=world["h_a"], user_id=world["admin"]) as session:
        with pytest.raises(ExportTooLarge) as caught:
            await collect_export(
                session,
                policy=POLICY,
                scope=ExportScope.HOUSEHOLD,
                subject_id=world["admin"],
                max_rows=1,
            )
    assert caught.value.limit == 1
    assert caught.value.rows > 1
