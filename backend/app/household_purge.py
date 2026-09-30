"""Der nächtliche Purge aufgelöster Haushalte (11-S1f, Art. 17).

Composition Root — hier treffen sich die Klassifizierung (``app/household_deletion_policy.py``) und
die Mechanik (``app/kernel/deletion/household.py``). Der Kernel kennt keine Tabellennamen, das Modul
keinen Cron (ADR-0039). Dasselbe Muster wie ``app/account_purge.py``, und aus demselben Grund.

**Der zweistufige Ablauf.** ``POST /v1/household/dissolve`` (11-S1e) beendet den Zugang **sofort**:
Haushalt getombstonet, alle Mitgliedschaften beendet, alle Sitzungen widerrufen, Kinder-Konten
vorgemerkt, Ökonomie abgewickelt, Art.-9-Daten hart gelöscht. Erst ``retention_days`` später räumt
dieser Job den Rest aus. Die Frist ist eine Purge-Verzögerung, **keine** Wiederherstellbarkeit —
ADR-0085 und KONZEPT Leitplanke 6 sagen das ausdrücklich, und die Oberfläche auch.

**Ein Haushalt je Transaktion, und darin alles oder nichts.** Zwischen Haushalten gilt das nicht:
einer, der an einer Besonderheit scheitert, darf die anderen dieser Nacht nicht mitreißen. Innerhalb
eines Haushalts schon — ein halb ausgeräumter Haushalt wäre ein Zustand, den niemand benennen kann,
und der nächste Lauf fände ihn als „fällig" wieder und liefe in dieselbe Wand. Dieselbe Aufteilung
wie beim Konto-Purge, dieselbe Begründung.

**Die Fälligkeit braucht keine zweite Spalte.** ``users`` bekam ``purged_at``, weil die Zeile
anonymisiert stehen bleibt und ``deleted_at`` allein nicht zugleich „vorgemerkt" und „erledigt"
heißen kann. Hier verschwindet die Zeile: ihr Fehlen **ist** „erledigt". Kein
``households.purged_at``, keine Migration.

**Fehlschläge gehen als eigene Meldung nach oben.** Ein Job, der nur bei Wirkung loggt, ist im
Fehlerfall stumm, und „gescheitert" sieht dann aus wie „nichts zu tun" — die Lehre, die der
Retention-Reaper drei Wochen lang bewiesen hat (BUGLOG 2026-07-31).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.household_deletion_policy import POLICY
from app.kernel.deletion.household import (
    HouseholdPurgeResult,
    delete_household_row,
    plan_purge,
    purge_tables,
)
from app.kernel.tenancy.session import maint_session, scoped_session
from app.logging import get_logger


@dataclass(frozen=True)
class HouseholdPurgeRun:
    """Was die Nacht gebracht hat — Zähler und Fehlschläge, nie Inhalte."""

    purged: list[HouseholdPurgeResult] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


async def find_due_households(*, retention_days: int) -> list[uuid.UUID]:
    """Aufgelöste Haushalte, deren Karenz abgelaufen ist.

    ``deleted_at IS NOT NULL`` heißt aufgelöst; dass die Zeile überhaupt noch existiert, heißt
    „noch nicht ausgeräumt". Läuft als ``custode_maint`` — die Rolle darf ``households`` lesen
    (Migration 0007), und der Job spannt naturgemäß über Haushalte.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with maint_session() as session:
        rows = await session.execute(
            text("SELECT id FROM households WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff"),
            {"cutoff": cutoff},
        )
        return [row[0] for row in rows.all()]


async def _identities(household_id: uuid.UUID) -> list[uuid.UUID]:
    """Unter welchen Identitäten der Durchgang laufen muss.

    Alle je zugehörigen Mitglieder — **einschließlich der getombstoneten**, denn die Auflösung
    tombstonet jede Mitgliedschaft, es gäbe sonst gar keine. Zwei Tabellen tragen eine
    mitglieds-gescopte Policy (ADR-0081); unter einer einzigen Identität bliebe deren Bestand für
    alle anderen liegen, ohne Fehler.

    Findet sich keine Mitgliedschaft mehr (etwa weil ein Konto-Purge sie zuvor entfernt hat), bleibt
    die Haushalts-Kennung als Identität: sie reicht für alles Haushaltsgescopte und ist dieselbe
    Notlösung wie in ``app/household_dissolution.py``.
    """
    async with maint_session() as session:
        rows = await session.execute(
            text("SELECT DISTINCT user_id FROM memberships WHERE household_id = :hid"),
            {"hid": household_id},
        )
        members = [row[0] for row in rows.all()]
    return members or [household_id]


async def purge_household(household_id: uuid.UUID) -> HouseholdPurgeResult:
    """Einen aufgelösten Haushalt endgültig ausräumen.

    Idempotent: ein zweiter Lauf findet keine Zeilen und keine ``households``-Zeile mehr.
    """
    identities = await _identities(household_id)
    counts: dict[str, int] = {}

    # Der Plan entsteht auf der ersten Sitzung und gilt für alle: das Schema ändert sich innerhalb
    # eines Laufs nicht, und ein zweites Ableiten wäre eine zweite Wahrheit.
    plan: list[str] | None = None
    for member_id in identities:
        async with scoped_session(household_id=household_id, user_id=member_id) as session:
            if plan is None:
                plan = await plan_purge(session, spec=POLICY)
            await purge_tables(session, tables=plan, counts=counts)

    # Die Haushaltszeile zuletzt und in einer eigenen Transaktion — alles andere ist dann weg, und
    # ihr Verschwinden markiert den Lauf als erledigt.
    async with scoped_session(household_id=household_id, user_id=identities[0]) as session:
        row_removed = await delete_household_row(session)

    return HouseholdPurgeResult(
        household_id=household_id, removed=counts, household_row_removed=row_removed
    )


async def purge_due_households(*, retention_days: int) -> HouseholdPurgeRun:
    """Alle fälligen Haushalte ausräumen — je Haushalt eigenständig."""
    run = HouseholdPurgeRun()
    for household_id in await find_due_households(retention_days=retention_days):
        try:
            run.purged.append(await purge_household(household_id))
        except SQLAlchemyError as exc:
            # Die Kennung darf im Log stehen: sie ist ein Schlüssel, kein Inhalt, und ohne sie ist
            # die Meldung für den Betrieb wertlos. Der Fehler**text** darf nicht — Postgres hängt
            # bei Constraint-Verletzungen ein „Failing row contains (…)" an, und das wären
            # Zeilendaten im Log. Stattdessen der SQLSTATE: fünf Zeichen, nie Inhalt, und genau der
            # Teil, der die Ursache benennt (`42501` = fehlende Rechte).
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            run.failed[str(household_id)] = f"{type(exc).__name__}:{sqlstate or 'unknown'}"
        except Exception as exc:
            # Bewusst breit: eine unklassifizierte Tabelle (`UnclassifiedTableError`) oder ein
            # unerwarteter Fehler darf diesen einen Haushalt kosten, nicht die ganze Nacht. Nur
            # der Ausnahmetyp wandert ins Log, nie die Meldung — sie könnte Tabellendaten tragen.
            run.failed[str(household_id)] = type(exc).__name__
    return run


async def run_purge(*, retention_days: int) -> HouseholdPurgeRun:
    """Einstiegspunkt des Cron. Protokolliert Wirkung **und** Fehlschlag."""
    log = get_logger("household_purge")
    run = await purge_due_households(retention_days=retention_days)
    if run.failed:
        log.error("household_purge_failed", households=len(run.failed), **run.failed)
    if run.purged:
        log.info(
            "household_purge_done",
            households=len(run.purged),
            rows=sum(result.total for result in run.purged),
        )
    return run
