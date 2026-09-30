"""Das endgültige Ausräumen eines Kontos nach der Karenz (Art. 17, KONZEPT §5.1/§9).

Der Kernel kennt keine Tabellennamen (E2, ADR-0039) — die Regeln kommen vom Composition Root
(``app/deletion_policy.py``), genau wie beim Retention-Reaper und beim Export.

**Eine Transaktion für das ganze Konto — und darin unterscheidet er sich bewusst vom Reaper.**
Der Reaper arbeitet seit BUGLOG 2026-07-31 *eine Transaktion je Tabelle* ab, damit eine scheiternde
Tabelle die anderen nicht mitreißt. Hier ist das genau falsch: ein halb ausgeräumtes Konto ist
schlimmer als ein gescheiterter Lauf. Bricht Schritt 9 von 14 ab, wäre ohne die gemeinsame
Transaktion ein Zustand entstanden, den niemand benennen kann — Sitzungen weg, Anmelde-Historie
weg, Tresor-Umschlag noch da, ``purged_at`` nicht gesetzt. Der nächste Lauf fände dasselbe Konto
wieder und liefe in dieselbe Wand. Also: alles oder nichts, und der Fehlschlag geht als eigene
Meldung nach oben (die andere Hälfte der Reaper-Lehre — ein Job, der nur bei Wirkung loggt, ist im
Fehlerfall stumm).

**Reihenfolge.** Zeilen zuerst, ``users`` zuletzt. Andersherum stünde zwischen Anonymisierung und
letztem DELETE ein Moment, in dem die Fachzeilen auf ein bereits ausgeräumtes Konto zeigen — und
falls die Transaktion dort abbricht, wäre genau das der bleibende Zustand.

**Was hier NICHT passiert:** die ``users``-Zeile wird nicht gelöscht. Sie bleibt anonymisiert
stehen, damit die 27 Verweise ohne Fremdschlüssel gültig bleiben (die Begründung steht in
``deletion_policy``). Was nicht in der Klassifizierung steht, wird nicht angefasst — Schweigen ist
hier kein Auftrag.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

# Wie im Reaper: Bezeichner sind codedefiniert (nie Nutzereingabe) und können nicht als Parameter
# gebunden werden. Ein Name, der hier durchfällt, ist ein Bug — deshalb abgelehnt statt escaped.
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):  # pragma: no cover - defensiv, Namen sind codedefiniert
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


@dataclass(frozen=True)
class PurgeResult:
    """Was der Purge bewegt hat — nur Zähler je Tabelle, nie Inhalte."""

    user_id: uuid.UUID
    removed: dict[str, int] = field(default_factory=dict)
    anonymised: bool = False

    @property
    def total(self) -> int:
        return sum(self.removed.values())


@dataclass(frozen=True)
class PurgeSpec:
    """Die Anweisung, was zu tun ist — vom Composition Root gefüllt.

    ``delete_columns``   (Tabelle, Spalte) — alle Zeilen mit diesem Personenbezug gehen.
    ``conditional``      (Tabelle, Spalte, Bedingungsspalte, Wert) — nur die passenden Zeilen.
    ``anonymise_user``   Spalte → Wert für die verbleibende ``users``-Zeile.
    """

    delete_columns: tuple[tuple[str, str], ...]
    conditional: tuple[tuple[str, str, str, str], ...]
    anonymise_user: dict[str, Any]


async def purge_user(session: AsyncSession, *, user_id: uuid.UUID, spec: PurgeSpec) -> PurgeResult:
    """Ein Konto endgültig ausräumen. Läuft in **einer** Transaktion des Aufrufers.

    Idempotent: ein zweiter Lauf findet keine Zeilen mehr und schreibt dieselben Werte in eine
    bereits anonymisierte Zeile.
    """
    removed: dict[str, int] = {}

    for table, column in spec.delete_columns:
        result = await session.execute(
            text(f"DELETE FROM {_ident(table)} WHERE {_ident(column)} = :uid"),  # noqa: S608
            {"uid": user_id},
        )
        count = cast("CursorResult[Any]", result).rowcount
        if count:
            removed[table] = removed.get(table, 0) + count

    for table, column, cond_column, cond_value in spec.conditional:
        result = await session.execute(
            text(
                f"DELETE FROM {_ident(table)} "  # noqa: S608
                f"WHERE {_ident(column)} = :uid AND {_ident(cond_column)} = :cond"
            ),
            {"uid": user_id, "cond": cond_value},
        )
        count = cast("CursorResult[Any]", result).rowcount
        if count:
            removed[table] = removed.get(table, 0) + count

    assignments = ", ".join(f"{_ident(c)} = :v_{c}" for c in spec.anonymise_user)
    # dict/list gehen an eine ``jsonb``-Spalte und muessen als JSON-Text gebunden werden — der
    # Treiber macht das nicht von selbst und quittiert es mit SQLSTATE 22000, also erst zur
    # Laufzeit. Die Klassifizierung soll `{}` sagen duerfen; die Uebersetzung ist Sache der
    # SQL-Schicht, nicht der Fachentscheidung.
    params: dict[str, Any] = {
        f"v_{c}": json.dumps(v) if isinstance(v, dict | list) else v
        for c, v in spec.anonymise_user.items()
    }
    params["uid"] = user_id
    params["now"] = datetime.now(UTC)
    statement = f"UPDATE users SET {assignments}, purged_at = :now WHERE id = :uid"  # noqa: S608
    result = await session.execute(text(statement), params)
    anonymised = bool(cast("CursorResult[Any]", result).rowcount)

    return PurgeResult(user_id=user_id, removed=removed, anonymised=anonymised)
