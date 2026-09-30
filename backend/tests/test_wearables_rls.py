"""RLS negative test for the wearables tables (Testcontainers PG 18, P9-S5, ADR-0081).

This is the core test of the slice. Every other fact table isolates by household and leaves
owner-only to the service layer; migration 0069 puts ``member_id`` INTO the policy because
health data is Art. 9 and N-2 forbids sharing it with co-members — including admins.

The decisive assertions are therefore not the usual household-vs-household ones but:
  * member X sees 0 rows of member Y **inside the same household**, on both tables
  * an admin gets exactly the same answer (the role is not in the predicate — that IS the point)
  * WITH CHECK refuses writing a row for somebody else

Skipped without Docker.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def _scope(conn: asyncpg.Connection, household: uuid.UUID, user: uuid.UUID) -> None:
    await conn.execute(
        "SELECT set_config('app.household_id', $1, false), set_config('app.user_id', $2, false);",
        str(household),
        str(user),
    )


async def _seed(container: PgDatabase, rows: list[tuple[uuid.UUID, uuid.UUID, str]]) -> None:
    """Insert connections + daily rows as the superuser (bypasses RLS)."""
    su = await _connect(container, container.username, container.password)
    try:
        for household, member, provider in rows:
            await su.execute(
                "INSERT INTO wearable_connections (household_id, member_id, provider) "
                "VALUES ($1,$2,$3);",
                household,
                member,
                provider,
            )
            await su.execute(
                "INSERT INTO wearable_daily "
                "(household_id, member_id, provider, day, sleep_score) "
                "VALUES ($1,$2,$3,CURRENT_DATE,80);",
                household,
                member,
                provider,
            )
    finally:
        await su.close()


async def test_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, [(h_a, member, "oura"), (h_b, member, "oura")])

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await _scope(app, h_a, member)
        assert (
            await app.fetchval(
                "SELECT count(*) FROM wearable_connections WHERE household_id=$1;", h_b
            )
            == 0
        )
        assert (
            await app.fetchval("SELECT count(*) FROM wearable_daily WHERE household_id=$1;", h_b)
            == 0
        )
    finally:
        await app.close()


async def test_rls_isolates_members_inside_one_household(migrated_pg: PgDatabase) -> None:
    """The heart of ADR-0081: co-members of the SAME household cannot see each other's rows.

    Against ``external_calendar_subscriptions`` this assertion would fail — there, owner-only is
    a service convention and the database happily returns the co-member's row."""
    household, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, [(household, alice, "oura"), (household, bob, "oura")])

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await _scope(app, household, alice)
        # Alice sees exactly her own row on both tables...
        assert await app.fetchval("SELECT count(*) FROM wearable_connections;") == 1
        assert await app.fetchval("SELECT member_id FROM wearable_connections;") == alice
        assert await app.fetchval("SELECT count(*) FROM wearable_daily;") == 1
        assert await app.fetchval("SELECT member_id FROM wearable_daily;") == alice
        # ...and cannot reach Bob's even when asking for it explicitly.
        assert (
            await app.fetchval("SELECT count(*) FROM wearable_connections WHERE member_id=$1;", bob)
            == 0
        )
        assert (
            await app.fetchval("SELECT count(*) FROM wearable_daily WHERE member_id=$1;", bob) == 0
        )
    finally:
        await app.close()


async def test_admin_has_no_privileged_read(migrated_pg: PgDatabase) -> None:
    """An admin is not special here. The policy predicate contains no role, so 'admin' is simply
    another ``app.user_id`` — exactly the guarantee N-2 asks for ("auch nicht für Admins")."""
    household, admin, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, [(household, member, "oura")])

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        # The admin is scoped to the same household but a different user id.
        await _scope(app, household, admin)
        assert await app.fetchval("SELECT count(*) FROM wearable_connections;") == 0
        assert await app.fetchval("SELECT count(*) FROM wearable_daily;") == 0
    finally:
        await app.close()


async def test_with_check_refuses_writing_for_someone_else(
    migrated_pg: PgDatabase,
) -> None:
    household, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await _scope(app, household, alice)
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO wearable_connections (household_id, member_id, provider) "
                "VALUES ($1,$2,'oura');",
                household,
                bob,  # foreign member_id -> WITH CHECK fires
            )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO wearable_daily (household_id, member_id, provider, day) "
                "VALUES ($1,$2,'oura',CURRENT_DATE);",
                household,
                bob,
            )
    finally:
        await app.close()


async def test_maint_can_enumerate_but_not_write(migrated_pg: PgDatabase) -> None:
    """The ingest cron enumerates connections across households read-only; every write goes
    through the member's own scoped session — that is the mechanism that makes N-2 hold for a
    background job, not a convention.

    Zwei Ausnahmen, beide mit einem Job dahinter, der sie braucht:

    * die 90-Tage-Retention (Migration 0070) loescht Rohwerte haushaltsuebergreifend — sie je
      Mitglied zu scopen waere sinnlos, weil sie ueber Einzelne nichts wissen muss;
    * der **Konto-Purge** (Migration 0072, 11-S1d) loescht die Verbindung selbst. Bis dahin galt
      hier „a connection is not a measurement — retention must never remove one", und fuer die
      *Retention* stimmt das weiterhin: ``wearable_connections`` steht nicht in
      ``_RETENTION_TABLES``, und diese Liste ist ihrerseits gegen die Datenbank geprueft.

    Warum die Grenze trotzdem verschoben wurde: laesst der Purge die Verbindung stehen, bleibt nach
    einer Kontoloeschung ein Art.-9-Datensatz zurueck. Der `member.left`-Handler raeumt sie zwar
    schon beim Austritt ab, aber eine endgueltige Loeschung darf sich nicht darauf verlassen, dass
    ein frueherer Schritt gelaufen ist — genau diese Annahme ist in dieser Phase mehrfach gebrochen.
    Ein zurueckgelassener Gesundheitsdatensatz wiegt schwerer als ein zusaetzliches DELETE-Recht
    fuer eine Rolle, deren Job-Listen ohnehin gated sind.

    Was UNVERAENDERT gilt und hier weiter geprueft wird: ``custode_maint`` darf **nicht
    schreiben**. Jede inhaltliche Aenderung laeuft ueber die eigene Session des Mitglieds — das ist
    der Mechanismus, der N-2 fuer einen Hintergrundjob traegt, keine Konvention."""
    h_c, h_d, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, [(h_c, member, "oura"), (h_d, member, "oura")])

    maint = await _connect(migrated_pg, "custode_maint", "maint")
    try:
        count = await maint.fetchval(
            "SELECT count(*) FROM wearable_connections WHERE household_id = ANY($1);", [h_c, h_d]
        )
        assert count == 2  # visible without any tenant scope
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await maint.execute("UPDATE wearable_connections SET status = 'needs_reauth';")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await maint.execute("UPDATE wearable_daily SET sleep_score = 1;")
        # Granted in 0070 (Retention) bzw. 0072 (Konto-Purge). Beide Jobs loeschen, keiner aendert.
        await maint.execute("DELETE FROM wearable_daily WHERE household_id = ANY($1);", [h_c, h_d])
        await maint.execute(
            "DELETE FROM wearable_connections WHERE household_id = ANY($1);", [h_c, h_d]
        )
    finally:
        await maint.close()


async def test_tombstones_are_forbidden(migrated_pg: PgDatabase) -> None:
    """Art. 9 wants deletion that deletes. The mixin carries ``deleted_at``, so a CHECK pins it
    to NULL — otherwise a future soft-delete would quietly retain health data for 30 days."""
    household, member = uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, [(household, member, "oura")])

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        for table in ("wearable_connections", "wearable_daily"):
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await su.execute(
                    f"UPDATE {table} SET deleted_at = now() WHERE member_id = $1;",  # noqa: S608
                    member,
                )
    finally:
        await su.close()


async def test_consent_ledger_stays_append_only_with_action(
    migrated_pg: PgDatabase,
) -> None:
    """Migration 0068 adds ``action`` without weakening the append-only property: a revoke is a
    new row, and the app role still has no UPDATE/DELETE grant."""
    household, member, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await _scope(app, household, member)
        await app.execute(
            "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
            "VALUES ($1,$2,'wearable_sleep','grant',$3), ($1,$2,'wearable_sleep','revoke',$3);",
            household,
            member,
            actor,
        )
        assert await app.fetchval("SELECT count(*) FROM consents;") == 2
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute("UPDATE consents SET action = 'grant';")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute("DELETE FROM consents;")
        # The CHECK rejects anything outside the vocabulary.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await app.execute(
                "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
                "VALUES ($1,$2,'wearable_sleep','maybe',$3);",
                household,
                member,
                actor,
            )
    finally:
        await app.close()
