"""Das Gate, das gefehlt hat: darf ``custode_maint`` wirklich jede Tabelle aus `_RETENTION_TABLES`
löschen? (Testcontainers PG 18, BUGLOG 2026-07-31)

Der Reaper hatte Tests — aber sie riefen ``reap_deleted(..., tables=("notes",))`` mit einem Literal
auf. ``_RETENTION_TABLES`` selbst kam in keinem Test vor. Als in Phase 9 zwei Tabellen in die Liste
wanderten, ohne die Rechte zu bekommen, die ``custode_maint`` dafür braucht, blieb alles grün —
während der nächtliche Job jede Nacht mit ``permission denied`` starb und (eine Transaktion für
alles) den ``notes``-Purge mitriss.

Die Lehre ist allgemeiner als der Bug: **eine Liste, die etwas über die Datenbank behauptet, muss
gegen die Datenbank geprüft werden, nicht gegen sich selbst.** Dasselbe Muster trägt das
Export-Gate (``tests/test_export_policy.py``) und der Compose-Test (``tests/test_compose_env.py``).

Ohne Docker übersprungen.
"""

from __future__ import annotations

import asyncpg

from app.worker import _RETENTION_TABLES
from conftest import PgDatabase


async def _maint(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user="custode_maint",
        password="maint",
        database=pg.dbname,
    )


async def test_the_reaper_may_read_and_delete_every_table_it_is_given(
    pg: PgDatabase,
) -> None:
    """Der Kern. Ohne Migration 0071 ist dieser Test rot für zwei von drei Tabellen."""
    conn = await _maint(pg)
    try:
        missing: list[str] = []
        for table in _RETENTION_TABLES:
            can_select = await conn.fetchval(
                "SELECT has_table_privilege('custode_maint', $1, 'SELECT');", table
            )
            can_delete = await conn.fetchval(
                "SELECT has_table_privilege('custode_maint', $1, 'DELETE');", table
            )
            if not (can_select and can_delete):
                missing.append(f"{table} (SELECT={can_select}, DELETE={can_delete})")
    finally:
        await conn.close()

    assert not missing, (
        "custode_maint fehlen Rechte auf Tabellen aus _RETENTION_TABLES: "
        + ", ".join(missing)
        + ". Der nächtliche Reaper stirbt damit an `permission denied`. Grants per Migration "
        "nachziehen (Muster: 0053_retention_maint.py / 0071_retention_grants.py)."
    )


async def test_every_reaped_table_has_the_maint_policy(pg: PgDatabase) -> None:
    """Grants allein genügen nicht: die Tabellen haben ``FORCE ROW LEVEL SECURITY``, und ohne eine
    permissive Policy für ``custode_maint`` sieht der Job schlicht null Zeilen — kein Fehler, nur
    ein stiller No-Op. Das wäre die schlimmere Variante des Bugs gewesen, weil nichts auffällt."""
    conn = await _maint(pg)
    try:
        without = [
            table
            for table in _RETENTION_TABLES
            if not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_policies "
                "WHERE tablename = $1 AND policyname = 'maint_all');",
                table,
            )
        ]
    finally:
        await conn.close()

    assert not without, (
        f"Tabellen ohne `maint_all`-Policy: {without}. Der Reaper sähe dort null Zeilen, "
        "ohne dass irgendetwas fehlschlägt."
    )


async def test_every_reaped_table_actually_has_a_tombstone_column(pg: PgDatabase) -> None:
    """Der Reaper filtert auf ``deleted_at``. Eine Tabelle ohne diese Spalte in der Liste wäre ein
    sofortiger Fehler — und eine mit ``CHECK (deleted_at IS NULL)`` (die Art.-9-Tabellen) gehört
    strukturell nicht hierher, weil sie nie getombstoned wird."""
    conn = await _maint(pg)
    try:
        for table in _RETENTION_TABLES:
            has_column = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = 'deleted_at');",
                table,
            )
            assert has_column, f"{table} hat keine Spalte `deleted_at`, wird aber gereapt"
    finally:
        await conn.close()


async def test_the_purge_statement_runs_for_real(pg: PgDatabase) -> None:
    """Rechte-Bits sind das eine, ein tatsächlich geplantes Statement das andere. Hier läuft die
    echte Anweisung aus dem Reaper — genau das, was jede Nacht gescheitert ist."""
    conn = await _maint(pg)
    try:
        for table in _RETENTION_TABLES:
            await conn.execute(
                f"DELETE FROM {table} WHERE deleted_at IS NOT NULL "  # noqa: S608
                f"AND deleted_at < now() - make_interval(days => 30)"
            )
    finally:
        await conn.close()
