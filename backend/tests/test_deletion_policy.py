"""Die Löschklassifizierung muss vollständig sein — geprüft gegen das echte Schema.

Warum nicht gegen ``Base.metadata``: **das ORM ist nicht das Schema.** Es kennt 29 Spalten der
echten Datenbank nicht (Views, generierte Spalten, reine Migrations-Tabellen), und genau in dieser
Lücke saßen beim Export ``tenancy_probe`` und ``guides.search_tsv``. Eine Liste, die etwas über
die Datenbank behauptet, wird gegen die Datenbank geprüft — sonst prüft sie sich selbst.

Die zweite Hälfte ist die Rückrichtung: eine Regel für eine Spalte, die es nicht (mehr) gibt, ist
ein stiller No-Op. Beim Purge sähe das aus wie „nichts zu tun".

Ohne Docker übersprungen.
"""

from __future__ import annotations

import asyncpg
import pytest

from app.deletion_policy import (
    ANONYMISE_USER,
    CONDITIONAL_DELETES,
    NOT_A_PERSON,
    PURGED_TABLES,
    RULES,
    Disposal,
)
from conftest import PgDatabase

# Die erste Fassung listete Namens-Suffixe („user_id", „member_id", „_by", …) und nannte sich
# „absichtlich zu breit". Sie war es nicht: `letters.from_id`, `notes.author_id`,
# `meal_slots.cook_id`, `guides.contact_id` und fünf weitere Personenbezüge fielen durch — gefunden
# nicht vom Gate, sondern beim Schreiben des E2E-Tests, weil ein Seed-INSERT auf eine Spalte lief,
# die es nicht gab.
#
# **Ein Muster, das „zu breit" heißt, muss zu breit BEWIESEN werden.** Deshalb jetzt die
# Umkehrung: jede Spalte auf `_id`/`_ids` gilt als personenverdächtig, bis sie eingeordnet ist —
# entweder als Regel in `RULES` oder ausdrücklich als Sachbezug in `NOT_A_PERSON`. Ein neuer
# Spaltenname kann damit nicht mehr durchrutschen, weil er zufällig anders heißt.
_SUFFIXES = ("_id", "_ids")


@pytest.fixture(scope="module")
def schema(pg: PgDatabase) -> list[tuple[str, str, str]]:
    """(Tabelle, Spalte, is_nullable) aus einer frisch migrierten Postgres 18."""
    import asyncio

    async def _fetch() -> list[tuple[str, str, str]]:
        conn = await asyncpg.connect(
            host=pg.get_container_host_ip(),
            port=pg.get_exposed_port(5432),
            user=pg.username,
            password=pg.password,
            database=pg.dbname,
        )
        try:
            rows = await conn.fetch(
                "SELECT table_name, column_name, is_nullable "
                "FROM information_schema.columns WHERE table_schema='public';"
            )
            return [(r["table_name"], r["column_name"], r["is_nullable"]) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_fetch())


def _is_reference(column: str) -> bool:
    return column.endswith(_SUFFIXES)


def test_every_reference_column_in_the_real_schema_is_classified(
    schema: list[tuple[str, str, str]],
) -> None:
    """Der eigentliche Gate — und er fällt geschlossen aus.

    Jede Spalte auf `_id`/`_ids` muss entweder eine Löschregel haben (Personenbezug) oder in
    `NOT_A_PERSON` als Sachbezug benannt sein. Schweigen ist keine Antwort: eine neue Spalte, die
    auf eine Person zeigt, ist eine Art.-17-Entscheidung, und niemandem fällt das beim Schreiben
    einer Migration von selbst ein.
    """
    classified = {(r.table, r.column) for r in RULES}
    unclassified = sorted(
        (table, column)
        for table, column, _ in schema
        if _is_reference(column)
        and table != "alembic_version"
        and (table, column) not in classified
        and column not in NOT_A_PERSON
    )
    assert unclassified == [], (
        "Diese Verweis-Spalten sind nicht eingeordnet. Jede braucht entweder eine Zeile in "
        "RULES (delete/keep/operator, mit Begründung) oder einen Eintrag in NOT_A_PERSON."
    )


def test_no_column_is_both_a_person_and_a_thing(schema: list[tuple[str, str, str]]) -> None:
    """Die Rückrichtung der Umkehrung.

    Stünde ein Spaltenname in beiden Listen, gewönne stillschweigend die Regel — und
    `NOT_A_PERSON` sähe aus wie eine Entscheidung, die nichts bewirkt."""
    overlaps = sorted({r.column for r in RULES} & set(NOT_A_PERSON))
    assert overlaps == []


def test_not_a_person_names_only_columns_that_exist(schema: list[tuple[str, str, str]]) -> None:
    """Ein Sachbezug, den es nicht mehr gibt, ist ein Freibrief für einen künftigen Namen."""
    real = {column for _, column, _ in schema}
    ghosts = sorted(set(NOT_A_PERSON) - real)
    assert ghosts == []


def test_no_rule_names_a_column_that_does_not_exist(schema: list[tuple[str, str, str]]) -> None:
    """Die Rückrichtung. Eine Regel für eine umbenannte Spalte löscht nichts und sieht dabei aus
    wie eine Regel, die nichts zu tun fand."""
    real = {(table, column) for table, column, _ in schema}
    ghosts = sorted({(r.table, r.column) for r in RULES} - real)
    assert ghosts == [], "Regeln ohne Spalte in der Datenbank — stille No-Ops"


def test_every_rule_carries_a_real_reason() -> None:
    """`reason` ist Pflicht und wird auf Substanz geprüft: „TODO" ist keine Klassifizierung."""
    weak = [
        f"{r.table}.{r.column}"
        for r in RULES
        if len(r.reason.strip()) < 15 or r.reason.strip().lower().startswith(("todo", "tbd", "?"))
    ]
    assert weak == []


def test_no_column_is_classified_twice() -> None:
    """Zwei Regeln für dieselbe Spalte hießen: eine davon ist wirkungslos, und welche entscheidet
    die Reihenfolge in einem Tupel."""
    seen = [(r.table, r.column) for r in RULES]
    assert len(seen) == len(set(seen))


def test_the_anonymised_user_columns_exist_and_accept_their_value(
    schema: list[tuple[str, str, str]],
) -> None:
    """`ANONYMISE_USER` behauptet etwas über `users` — nämlich, dass jede genannte Spalte existiert
    und den Wert annimmt. Ein `None` auf eine `NOT NULL`-Spalte fiele sonst erst beim nächtlichen
    Purge auf, im Cron, ohne Zuschauer."""
    users = {column: nullable for table, column, nullable in schema if table == "users"}
    missing = sorted(set(ANONYMISE_USER) - set(users))
    assert missing == [], "ANONYMISE_USER nennt Spalten, die es in `users` nicht gibt"

    not_nullable = sorted(
        column
        for column, value in ANONYMISE_USER.items()
        if value is None and users[column] == "NO"
    )
    assert not_nullable == [], "None auf eine NOT-NULL-Spalte — das schlägt erst zur Laufzeit fehl"


def test_every_conditional_delete_names_real_columns(schema: list[tuple[str, str, str]]) -> None:
    """Der Sonderfall hängt an zwei Spalten — der Personen-Spalte und der Bedingungs-Spalte. Fehlt
    eine, löscht der Purge entweder nichts oder das Falsche, und beides sieht gleich aus."""
    real = {(t, c) for t, c, _ in schema}
    for rule in CONDITIONAL_DELETES:
        assert (rule.table, rule.column) in real
        assert (rule.table, rule.condition[0]) in real


def test_purged_tables_is_derived_and_complete(schema: list[tuple[str, str, str]]) -> None:
    """PURGED_TABLES ist abgeleitet, nicht gepflegt — eine handgeschriebene Zweitliste wäre genau
    die Konstruktion, an der der Retention-Reaper gescheitert ist. Der Test hält fest, dass die
    Ableitung stimmt und jede Tabelle existiert."""
    expected = {r.table for r in RULES if r.disposal is Disposal.delete}
    expected |= {c.table for c in CONDITIONAL_DELETES}
    assert set(PURGED_TABLES) == expected
    real_tables = {t for t, _, _ in schema}
    assert set(PURGED_TABLES) <= real_tables


def test_the_ledger_is_never_deleted() -> None:
    """Eine Invariante, kein Geschmack: der Ledger ist eine doppelte Buchführung (ADR-0035). Eine
    Buchung zu löschen veränderte die Salden **anderer** — der Danke-Punkt gehört beiden Seiten.
    Diese Zeile hier ist billiger als die Frage, warum Salden nicht mehr aufgehen."""
    ledger = [r for r in RULES if r.table in {"points_ledger", "redemptions", "market_listings"}]
    assert ledger, "die Ökonomie-Tabellen müssen klassifiziert sein"
    assert all(r.disposal is Disposal.keep for r in ledger)
