"""Das Export-Gate gegen die ECHTE Datenbank (Testcontainers PG 18).

Warum es das zusätzlich zu ``tests/test_export_policy.py`` gibt: jenes prüft gegen
``Base.metadata`` — also gegen das, was die Anwendung *deklariert*. Der Export liest aber
``SELECT * FROM <tabelle>``, und die Datenbank hat mehr, als das ORM kennt:

* **Tabellen nur in Migrationen.** ``tenancy_probe`` (Migration 0001) hat RLS, volle DML-Grants für
  ``custode_app`` und kein ORM-Modell. Sie war für das ORM-Gate unsichtbar und wäre stillschweigend
  weder exportiert noch bewusst ausgeschlossen gewesen.
* **Spalten nur in Migrationen.** ``guides.search_tsv`` ist ``GENERATED ALWAYS … STORED``; das
  Modell sagt ausdrücklich „read-only, not mapped here". Sie landet trotzdem im Export, weil
  ``SELECT *`` sie mitbringt — und das namensbasierte Redaktions-Gate könnte sie nicht einmal
  sehen.

Beides ist im konkreten Fall harmlos. **Der Befund ist das Loch, nicht der Schaden:** die nächste
generierte Spalte oder Hilfstabelle fällt genauso durch, und dann ist es vielleicht keine
Ableitung aus ohnehin exportierten Feldern mehr.

Geprüft wird deshalb aus der Perspektive, die zählt: **was darf ``custode_app`` lesen?** Alles, was
diese Rolle sehen kann, kann im Export landen.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import re

import asyncpg

# Dieselbe Liste wie im ORM-Gate — bewusst dupliziert statt importiert: ein Test soll nicht davon
# abhängen, dass ein anderer Test seine Konstanten behält.
from tests.test_export_policy import _REVIEWED_SAFE, _SENSITIVE_NAME

from app.export_policy import EXCLUDED, EXPORTED, POLICY
from conftest import PgDatabase

_EXPORTED_NAMES = {spec.name for spec in EXPORTED}


async def _connect(pg: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=user,
        password=password,
        database=pg.dbname,
    )


async def _readable_objects(conn: asyncpg.Connection) -> set[str]:
    """Alles in ``public``, was ``custode_app`` lesen darf — Tabellen **und** Views."""
    rows = await conn.fetch(
        """
        SELECT c.relname AS name
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'v', 'm', 'p')
          AND has_table_privilege('custode_app', c.oid, 'SELECT');
        """
    )
    return {r["name"] for r in rows}


async def test_everything_the_app_role_can_read_is_classified(pg: PgDatabase) -> None:
    """Der Kern. Was ``custode_app`` lesen darf, kann im Export landen — also braucht es eine
    Entscheidung. Ohne den Eintrag für `tenancy_probe` ist dieser Test rot."""
    conn = await _connect(pg, "custode_app", "app")
    try:
        readable = await _readable_objects(conn)
    finally:
        await conn.close()

    unclassified = sorted(readable - (_EXPORTED_NAMES | set(EXCLUDED)))
    assert not unclassified, (
        "In der Datenbank lesbar, aber in app/export_policy.py nicht klassifiziert: "
        + ", ".join(unclassified)
        + ". Entweder zu EXPORTED (mit `shared`/`personal_columns`) oder zu EXCLUDED mit "
        "Begründung. Das ORM-Gate sieht diese Objekte nicht — sie stehen nur in einer Migration."
    )


async def test_the_classification_has_no_dead_entries(pg: PgDatabase) -> None:
    """Gegenrichtung: ein Eintrag für ein Objekt, das es nicht mehr gibt, ist eine Karteileiche —
    beim nächsten Umbenennen glaubte man, etwas sei geregelt, was niemand mehr prüft."""
    conn = await _connect(pg, "custode_app", "app")
    try:
        rows = await conn.fetch(
            "SELECT c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind IN ('r','v','m','p');"
        )
        existing = {r["name"] for r in rows}
    finally:
        await conn.close()

    ghosts = sorted((_EXPORTED_NAMES | set(EXCLUDED)) - existing)
    assert not ghosts, f"Export-Policy nennt nicht (mehr) existierende Objekte: {ghosts}"


async def test_no_secret_looking_db_column_slips_into_an_export(pg: PgDatabase) -> None:
    """Dasselbe Redaktions-Gate wie im ORM-Test, aber über die **Datenbank**-Spalten.

    ``guides.search_tsv`` ist der Beleg, dass die beiden Mengen auseinandergehen: generiert,
    nicht gemappt, aber von ``SELECT *`` mitgebracht.
    """
    conn = await _connect(pg, "custode_app", "app")
    try:
        findings: list[str] = []
        for spec in EXPORTED:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1;",
                spec.name,
            )
            redacted = POLICY.redact.get(spec.name, frozenset())
            for row in rows:
                column = row["column_name"]
                if not _SENSITIVE_NAME.search(column):
                    continue
                if column in redacted or f"{spec.name}.{column}" in _REVIEWED_SAFE:
                    continue
                findings.append(f"{spec.name}.{column}")
    finally:
        await conn.close()

    assert not findings, (
        "Spalte(n) mit geheimnisverdächtigem Namen liegen in der Datenbank und würden exportiert: "
        + ", ".join(sorted(findings))
        + ". In _REDACT aufnehmen oder in _REVIEWED_SAFE begründen."
    )


async def test_the_db_has_columns_the_orm_does_not_know(pg: PgDatabase) -> None:
    """Kein Fehler, sondern der Nachweis, dass dieses Gate nötig ist.

    Findet die Differenz zwischen Datenbank und ORM je exportierter Tabelle. Wird sie eines Tages
    leer, war dieser Test trotzdem richtig — dann bewacht er, dass sie leer bleibt.
    """
    import app.main  # noqa: F401  — lädt alle Modelle
    from app.kernel.db.base import Base

    conn = await _connect(pg, "custode_app", "app")
    try:
        differences: dict[str, list[str]] = {}
        for spec in EXPORTED:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1;",
                spec.name,
            )
            db_columns = {r["column_name"] for r in rows}
            orm_columns = {c.name for c in Base.metadata.tables[spec.name].columns}
            extra = sorted(db_columns - orm_columns)
            if extra:
                differences[spec.name] = extra
    finally:
        await conn.close()

    # Stand 2026-07-31: genau eine. Ändert sich das, gehört die neue Spalte geprüft — deshalb
    # steht hier eine Gleichheit und keine Obergrenze.
    assert differences == {"guides": ["search_tsv"]}, (
        f"Die Differenz Datenbank↔ORM hat sich geändert: {differences}. Jede neue Spalte, die nur "
        "in der Datenbank existiert, landet über `SELECT *` im Export, ohne dass das ORM-Gate sie "
        "sieht — prüfen und hier festschreiben."
    )


def test_sensitive_pattern_is_shared_not_reinvented() -> None:
    """Beide Gates müssen dieselbe Vorstellung von „sieht geheim aus" haben, sonst schützt das eine
    vor etwas, das das andere durchlässt."""
    assert isinstance(_SENSITIVE_NAME, re.Pattern)
    assert _SENSITIVE_NAME.search("tokens_enc")
    assert not _SENSITIVE_NAME.search("title")
