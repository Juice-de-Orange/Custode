"""Was beim Austritt aus einem Haushalt in welcher Reihenfolge geschieht (KONZEPT §5.1).

**Warum das hier liegt und nicht in einem Modul.** Der Austritt berührt vier Module — Marketplace,
Tasks, Economy, dazu Kalender und Wearables über eigene Handler. Kein Modul darf ein anderes
importieren; jeder Versuch, die Abfolge *innerhalb* eines Moduls zu orchestrieren, wäre eine
Grenzverletzung. Der Composition Root ist genau der Ort, an dem Quermodul-Abläufe zusammenlaufen
dürfen (ADR-0039, Muster: die Outbox-Handler-Registrierung in ``app/worker.py``).

**Die Reihenfolge ist der Inhalt dieses Moduls, nicht seine Verpackung.** Sie ergibt sich aus dem
Ledger, nicht aus Geschmack:

1. **Handelspositionen auflösen.** Offene Verkäufe zurückziehen (Escrow zurück an die Person),
   angenommene Käufe rückabwickeln (Escrow zurück an den Verkäufer, Aufgabe zurück an ihn).
2. **Aufgaben freigeben.** Was der Person zugewiesen war und offen ist, geht in den Pool zurück.
3. **Restsaldo verfallen lassen** (``ref_type='member_exit'``).

Schritt 3 muss **zuletzt** laufen. Andersherum käme das in Schritt 1 freigegebene Escrow *nach*
dem Verfall auf dem Konto an und läge dort für immer — auf einem Konto, das keine Route mehr
auflöst, weil die Mitgliedschaft weg ist. Das ist kein theoretischer Fall: `withdraw_listing`
prüft `seller_id`, und die Person ist dann keine mehr.

Schritt 2 steht zwischen beiden, weil ``revert_listing`` selbst eine Aufgabe zurückgibt — erst
danach ist der Bestand der Zuweisungen stabil.

Was hier **nicht** passiert: Kalender-Feed, CalDAV-Abos und Wearables hängen als eigene
Outbox-Handler an ``member.left`` (11-S1a). Sie sind voneinander und von diesem Ablauf unabhängig;
eine gemeinsame Reihenfolge bräuchten sie nur, wenn sie sich beeinflussten, und das tun sie nicht.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import maint_session, scoped_session
from app.logging import get_logger
from app.modules.accounts.models import Household
from app.modules.economy import api as economy_api
from app.modules.marketplace import api as marketplace_api
from app.modules.tasks import api as tasks_api

_HANDLER_NAME = "app.settle_member_exit"  # stabiler Idempotenz-Schlüssel — nie umbenennen


@dataclass(frozen=True)
class ExitSettlement:
    """Was der Austritt bewegt hat — nur Zähler, nie Inhalte."""

    withdrawn: int = 0
    reverted: int = 0
    tasks_released: int = 0
    points_expired: int = 0


async def settle_member_exit(*, household_id: uuid.UUID, member_id: uuid.UUID) -> ExitSettlement:
    """Die drei Schritte in einer Transaktion. Idempotent: ein zweiter Lauf findet keine offenen
    Positionen, keine Zuweisungen und Saldo 0."""
    async with scoped_session(household_id=household_id, user_id=member_id) as session:
        positions = await marketplace_api.release_positions_of(
            session, household_id=household_id, member_id=member_id
        )
        released = await tasks_api.release_assignments_of(
            session, household_id=household_id, member_id=member_id
        )
        expired = await economy_api.expire_member_balance(
            session, household_id=household_id, member_id=member_id
        )
    return ExitSettlement(
        withdrawn=positions["withdrawn"],
        reverted=positions["reverted"],
        tasks_released=released,
        points_expired=expired,
    )


async def on_member_left(event: EventEnvelope) -> None:
    raw_id = event.payload.get("user_id")
    if not raw_id:
        return
    # Bei einer Haushalts-AUFLÖSUNG macht `app/household_dissolution.py` die Ökonomie — über alle
    # Mitglieder in fester Reihenfolge. Dieser Handler steigt dann aus, und zwar NICHT aus
    # Idempotenz-Gründen (die Operationen sind idempotent), sondern weil `FOR UPDATE SKIP LOCKED`
    # zwei Workern erlaubt, `household.dissolved` und ein `member.left` desselben Haushalts
    # gleichzeitig zu ziehen. Dann wäre die Reihenfolge wieder offen, und freigegebenes Escrow
    # käme nach dem Verfall an — auf einem Konto, das keine Route mehr auflöst (ADR-0085).
    if await _household_is_dissolved(event.household_id):
        get_logger("member_exit").info("member_exit_skipped_dissolved")
        return
    settlement = await settle_member_exit(
        household_id=event.household_id, member_id=uuid.UUID(raw_id)
    )
    get_logger("member_exit").info(
        "member_exit_settled",
        withdrawn=settlement.withdrawn,
        reverted=settlement.reverted,
        tasks_released=settlement.tasks_released,
        points_expired=settlement.points_expired,
    )


async def _household_is_dissolved(household_id: uuid.UUID) -> bool:
    """Ob der Haushalt aufgelöst ist. Läuft als ``custode_maint``: der Handler hat keine
    Mitglieds-Identität, und die Mitgliedschaften sind zu diesem Zeitpunkt alle getombstonet."""
    async with maint_session() as session:
        deleted_at = await session.scalar(
            select(Household.deleted_at).where(Household.id == household_id)
        )
    return deleted_at is not None


def register_member_exit_handler(dispatcher: OutboxDispatcher) -> None:
    """Bindet den Ablauf. Einmal am Composition Root aufgerufen (Worker-Start)."""
    dispatcher.register("member.left", _HANDLER_NAME, on_member_left)
