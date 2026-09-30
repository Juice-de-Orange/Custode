"""Der nächtliche Purge: Konten, deren Karenz abgelaufen ist, endgültig ausräumen (11-S1d).

Composition Root — hier treffen sich die Klassifizierung (``app/deletion_policy.py``) und die
Mechanik (``app/kernel/deletion``). Der Kernel kennt keine Tabellennamen, das Modul kennt keinen
Cron (ADR-0039).

**Der zweistufige Ablauf und warum er so aussieht.** ``DELETE /v1/auth/account`` (11-S1c) sperrt
sofort und setzt ``deleted_at``; der Austritt aus allen Haushalten geschieht ebenfalls sofort.
Erst ``retention_days`` später räumt dieser Job auf. Die Frist schützt vor der Fehlbedienung und
vor einem übernommenen Konto — sie ist **kein** Grund, in der Zwischenzeit weiter Daten zu
sammeln, und das tut auch nichts mehr.

**Ein Konto je Transaktion.** Innerhalb eines Kontos gilt alles-oder-nichts (Begründung in
``kernel/deletion/purge``); *zwischen* Konten aber nicht: ein Konto, das an einer Besonderheit
scheitert, darf die anderen dieser Nacht nicht mitreißen. Das ist dieselbe Aufteilung, die der
Retention-Reaper seit BUGLOG 2026-07-31 hat — nur eine Ebene höher.

**Fehlschläge gehen als eigene Meldung nach oben.** Ein Job, der nur bei Wirkung loggt, ist im
Fehlerfall stumm, und „gescheitert" sieht dann aus wie „nichts zu tun". Dieselbe Lehre, dieselbe
Umsetzung wie beim Reaper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.deletion_policy import ANONYMISE_USER, CONDITIONAL_DELETES, RULES, Disposal
from app.kernel.deletion import PurgeResult, PurgeSpec, purge_user
from app.kernel.tenancy.session import maint_session
from app.logging import get_logger


def build_purge_spec() -> PurgeSpec:
    """Die Klassifizierung in die Anweisung übersetzen, die der Kernel ausführt.

    Bewusst **abgeleitet** statt danebengeschrieben: eine zweite, handgepflegte Liste wäre genau
    die Konstruktion, an der der Retention-Reaper gescheitert ist — sie behauptet etwas über die
    erste und niemand prüft es.
    """
    return PurgeSpec(
        delete_columns=tuple(
            (rule.table, rule.column) for rule in RULES if rule.disposal is Disposal.delete
        ),
        conditional=tuple(
            (rule.table, rule.column, rule.condition[0], rule.condition[1])
            for rule in CONDITIONAL_DELETES
        ),
        anonymise_user=dict(ANONYMISE_USER),
    )


@dataclass(frozen=True)
class PurgeRun:
    """Was die Nacht gebracht hat — Zähler und Fehlschläge, nie Inhalte oder Kennungen von Personen
    im Klartext-Log."""

    purged: list[PurgeResult] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


async def find_due_accounts(*, retention_days: int) -> list[uuid.UUID]:
    """Konten, deren Karenz abgelaufen ist und die noch nicht ausgeräumt sind.

    ``purged_at IS NULL`` ist der Grund, warum es die zweite Spalte gibt: ``deleted_at`` allein
    kann nicht zugleich „vorgemerkt" und „erledigt" bedeuten, und ein zweiter Lauf sähe sonst
    jede Nacht dieselben Zeilen wieder als fällig.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with maint_session() as session:
        rows = await session.execute(
            text(
                "SELECT id FROM users "
                "WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff AND purged_at IS NULL"
            ),
            {"cutoff": cutoff},
        )
        return [row[0] for row in rows.all()]


async def purge_due_accounts(*, retention_days: int) -> PurgeRun:
    """Alle fälligen Konten ausräumen — je Konto eine Transaktion."""
    spec = build_purge_spec()
    run = PurgeRun()
    for user_id in await find_due_accounts(retention_days=retention_days):
        try:
            async with maint_session() as session:
                run.purged.append(await purge_user(session, user_id=user_id, spec=spec))
        except SQLAlchemyError as exc:
            # Die Kennung darf hier stehen: sie ist ein Schlüssel, kein Inhalt, und ohne sie ist
            # die Meldung für den Betrieb wertlos.
            #
            # Der Fehler**text** darf NICHT: Postgres hängt bei Constraint-Verletzungen ein
            # „Failing row contains (…)" an, und das wären Zeilendaten im Log. Stattdessen der
            # SQLSTATE — ein fünfstelliger Code, nie Inhalt, und genau der Teil, der die Ursache
            # benennt (`42501` = permission denied). Ohne ihn stünde im Log „irgendwas ging
            # schief", und der Betrieb wüsste nicht, ob Rechte, Constraint oder Verbindung.
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            run.failed[str(user_id)] = f"{type(exc).__name__}:{sqlstate or 'unknown'}"
    return run


async def run_purge(*, retention_days: int) -> PurgeRun:
    """Einstiegspunkt des Cron. Protokolliert Wirkung **und** Fehlschlag."""
    log = get_logger("account_purge")
    run = await purge_due_accounts(retention_days=retention_days)
    if run.failed:
        log.error("account_purge_failed", accounts=len(run.failed), **run.failed)
    if run.purged:
        log.info(
            "account_purge_done",
            accounts=len(run.purged),
            rows=sum(result.total for result in run.purged),
        )
    return run
