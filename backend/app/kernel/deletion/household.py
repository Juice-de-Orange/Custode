"""Das endgültige Ausräumen eines aufgelösten Haushalts (Art. 17, 11-S1f, ADR-0085 §7 / ADR-0086).

Der Kernel kennt **keine Tabellennamen** (E2, ADR-0039) — und das ist hier keine Stilfrage, sondern
die Bauanleitung: die Menge wird **abgeleitet**, nicht gepflegt. Kein Fremdschlüssel zeigt auf
``households.id`` (gegen die echte Datenbank geprüft, 0 Treffer), die Datenbank kann eine vergessene
Tabelle also **nie** melden. Eine handgeschriebene Liste wäre exakt ``_RETENTION_TABLES``
(BUGLOG 2026-07-31), nur mit 41 statt 3 Einträgen.

**Die Reihenfolge kommt aus ``pg_constraint``.** Fünf Fremdschlüssel zwischen den
haushaltsgebundenen Tabellen stehen auf ``NO ACTION`` und binden auch *innerhalb* einer Transaktion
(keiner ist ``DEFERRABLE``): ``task_instances → task_templates → rooms``,
``recipe_ingredients → recipes``, ``shopping_items → shopping_lists``, ``redemptions → rewards``.
Kinder zuerst, Eltern danach.

**Gelöscht wird als ``custode_app`` unter RLS, nicht als ``custode_maint`` mit WHERE-Klausel**
(ADR-0085, verworfene Alternative). Das DELETE nennt den Haushalt gar nicht — die Policy tut es.
Damit bleibt die Mandantengrenze dieselbe wie im Rest des Systems: es gibt keinen Filter, den man
vergessen kann, und keine 27 zusätzlichen Grants für die Wartungsrolle.

**Und deshalb läuft der Durchgang einmal je Mitglied.** Zwei Tabellen tragen eine *mitglieds*-
gescopte Policy (``wearable_connections``, ``wearable_daily``, ADR-0081): unter der Identität eines
einzelnen Mitglieds meldet ein DELETE dort erfolgreich „0 Zeilen" und lässt die Art.-9-Daten aller
anderen liegen — **ohne Fehler**. Statt diese zwei Tabellen zu *benennen* (eine Repräsentation, die
beim nächsten mitglieds-gescopten Modul veraltet, und genau die Fehlerklasse, die diese Codebasis
fünfmal bezahlt hat), wiederholt der Lauf jede Tabelle unter jeder Mitglieds-Identität. Die
Datenbank entscheidet, was jede Sitzung sehen darf; dieser Code muss es nicht wissen. Für
haushaltsgescopte Tabellen räumt der erste Durchgang alles ab, die übrigen treffen 0 Zeilen — bei
einer Handvoll Mitgliedern ein paar Dutzend wirkungslose Anweisungen und kein Grund für eine
Sonderliste.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

# Wie im Reaper und im Konto-Purge: Bezeichner sind codedefiniert (hier: aus dem Katalog gelesen)
# und können nicht als Parameter gebunden werden. Ein Name, der hier durchfällt, ist ein Bug —
# deshalb abgelehnt statt escaped.
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

# Alle Basistabellen mit einer Spalte `household_id`. Der Katalog ist die Quelle, nicht das ORM:
# `tenancy_probe` und `guides.search_tsv` haben beim Export bewiesen, dass `Base.metadata` das
# Schema nur teilweise kennt (ADR-0083).
_HOUSEHOLD_TABLES = text(
    """
    SELECT c.relname AS table_name
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE a.attname = 'household_id'
      AND NOT a.attisdropped
      AND n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
    """
)

# Fremdschlüssel zwischen zwei Tabellen. `confdeltype` wird bewusst nicht ausgewertet: auch ein
# CASCADE-Kind darf zuerst fallen, es kostet nur nichts — und eine Unterscheidung wäre eine weitere
# Annahme, die stillschweigend veralten kann.
_FOREIGN_KEYS = text(
    """
    SELECT src.relname AS child, tgt.relname AS parent
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class tgt ON tgt.oid = con.confrelid
    JOIN pg_namespace n ON n.oid = src.relnamespace
    WHERE con.contype = 'f' AND n.nspname = 'public' AND src.relname <> tgt.relname
    """
)


def _ident(name: str) -> str:
    if not _IDENT.match(name):  # pragma: no cover - defensiv, Namen kommen aus dem Katalog
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


class UnclassifiedTableError(RuntimeError):
    """Eine abgeleitete Tabelle, die die Klassifizierung nicht kennt.

    Der Lauf bricht ab, statt zu raten. Beide möglichen Vermutungen wären falsch: löschen zerstörte
    Daten, über die niemand entschieden hat; überspringen ließe personenbezogene Zeilen eines
    aufgelösten Haushalts liegen und meldete trotzdem Erfolg.
    """


@dataclass(frozen=True)
class HouseholdPurgeSpec:
    """Die Einordnung je Tabelle, vom Composition Root gefüllt.

    ``delete_tables`` — daraus wird alles entfernt, was der Haushalt besitzt.
    ``keep_tables``   — bleibt ausdrücklich stehen (Begründung je Tabelle im Root).
    """

    delete_tables: frozenset[str]
    keep_tables: frozenset[str]


@dataclass(frozen=True)
class HouseholdPurgeResult:
    """Was der Lauf bewegt hat — nur Zähler je Tabelle, nie Inhalte."""

    household_id: uuid.UUID
    removed: dict[str, int] = field(default_factory=dict)
    household_row_removed: bool = False

    @property
    def total(self) -> int:
        return sum(self.removed.values())


async def discover_household_tables(session: AsyncSession) -> list[str]:
    """Alle Basistabellen mit ``household_id`` — aus dem Katalog, nicht aus einer Liste."""
    rows = await session.execute(_HOUSEHOLD_TABLES)
    return [str(row[0]) for row in rows.all()]


async def _edges(session: AsyncSession, tables: set[str]) -> list[tuple[str, str]]:
    rows = await session.execute(_FOREIGN_KEYS)
    return [
        (str(child), str(parent))
        for child, parent in rows.all()
        if str(child) in tables and str(parent) in tables
    ]


def order_children_first(tables: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Topologisch sortieren: ein Kind steht **vor** seinem Elternteil.

    ``edges`` sind Paare ``(Kind, Elternteil)`` — das Kind referenziert den Elternteil. Eine Tabelle
    darf fallen, sobald keine **verbleibende** Tabelle sie als Elternteil braucht.

    Bei Gleichstand alphabetisch: eine Reihenfolge, die von der Laufzeit abhängt, macht jeden
    Fehlschlag unreproduzierbar. Zyklen (heute keine) werden **nicht** wegsortiert, sondern
    unverändert angehängt — ein DELETE, das dann an einem Constraint scheitert, ist ein lauter
    Fehler und genau das, was wir wollen.
    """
    parents_of: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in edges:
        if child in parents_of and parent in parents_of:
            parents_of[child].add(parent)

    ordered: list[str] = []
    remaining = sorted(tables)
    while remaining:
        ready = [t for t in remaining if not any(t in parents_of[o] for o in remaining if o != t)]
        if not ready:  # pragma: no cover - im aktuellen Schema zyklenfrei
            ordered.extend(remaining)
            break
        ordered.extend(ready)
        done = set(ready)
        remaining = [t for t in remaining if t not in done]
    return ordered


async def plan_purge(session: AsyncSession, *, spec: HouseholdPurgeSpec) -> list[str]:
    """Die zu leerenden Tabellen in der Reihenfolge, in der sie fallen dürfen.

    Läuft **vor** dem ersten DELETE und bricht ab, sobald das Schema eine Tabelle kennt, die die
    Klassifizierung nicht kennt. Die Prüfung gehört an den Anfang, nicht ans Ende: ein Abbruch nach
    dem halben Ausräumen hinterließe genau den Zustand, den die gemeinsame Transaktion verhindern
    soll.
    """
    discovered = await discover_household_tables(session)
    known = spec.delete_tables | spec.keep_tables
    unknown = sorted(set(discovered) - known)
    if unknown:
        raise UnclassifiedTableError(
            "Haushaltsgebundene Tabellen ohne Einordnung in app/household_deletion_policy.py: "
            + ", ".join(unknown)
        )
    targets = [t for t in discovered if t in spec.delete_tables]
    return order_children_first(targets, await _edges(session, set(targets)))


async def purge_tables(session: AsyncSession, *, tables: list[str], counts: dict[str, int]) -> None:
    """Die Tabellen in der übergebenen Reihenfolge leeren — auf **dieser** Sitzung.

    Das DELETE nennt den Haushalt nicht; die RLS-Policy der Sitzung tut es. Was diese Sitzung nicht
    sehen darf, löscht sie nicht — genau deshalb ruft der Aufrufer sie je Mitglied.
    """
    for table in tables:
        result = await session.execute(text(f"DELETE FROM {_ident(table)}"))  # noqa: S608
        count = cast("CursorResult[Any]", result).rowcount
        if count:
            counts[table] = counts.get(table, 0) + count


async def delete_household_row(session: AsyncSession) -> bool:
    """Die ``households``-Zeile selbst — zuletzt, und ebenfalls ohne WHERE.

    Ihr Fehlen **ist** die Markierung „ausgeräumt"; es braucht keine zweite Spalte, die dasselbe
    behauptet, und damit keine Migration. Kein Fremdschlüssel zeigt auf sie;
    ``audit_log.household_id`` bleibt als nackte Kennung bestehen (ADR-0084: sie bezeichnet den
    Haushalt, nicht die Person).
    """
    result = await session.execute(text("DELETE FROM households"))
    return bool(cast("CursorResult[Any]", result).rowcount)
