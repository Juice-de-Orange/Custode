"""Was bei der Auflösung eines Haushalts mit der Ökonomie geschieht — über **alle** Mitglieder.

Composition Root, aus demselben Grund wie ``app/member_exit.py``: der Ablauf berührt Marketplace,
Tasks und Economy, und kein Modul darf ein anderes importieren (ADR-0039).

**Warum es dieses Modul überhaupt gibt — und nicht einfach n-mal ``settle_member_exit``.**
``revert_listing`` kreditiert beim Rückabwickeln den **Verkäufer** (das Escrow fließt an ihn
zurück). Liefe die Abwicklung mitgliedsweise, könnte der Saldo des Verkäufers längst verfallen
sein, wenn das Escrow des Käufers zurückkommt — die Punkte stranden dann auf einem Konto, das keine
Mitgliedschaft mehr hat und für das keine Route mehr einen Saldo auflöst.

Beim **Einzelaustritt** ist das unmöglich: dort geht genau eine Person, und die Gegenseite bleibt.
Bei der **Auflösung** ist es der Normalfall, weil alle gleichzeitig gehen.

Deshalb dieselbe Reihenfolge wie in ``member_exit``, aber eine Ebene höher gezogen:

1. **erst alle** Handelspositionen auflösen,
2. **dann alle** Aufgaben freigeben,
3. **dann alle** Restsalden verfallen lassen.

Schritt 3 zuletzt und über alle Mitglieder hinweg — das ist der ganze Punkt. Andersherum käme
freigegebenes Escrow *nach* dem Verfall an.

**Und deshalb steigt ``on_member_left`` bei einem aufgelösten Haushalt aus** (siehe
``app/member_exit.py``). Nicht aus Idempotenz-Gründen — die Operationen sind idempotent —, sondern
weil ``FOR UPDATE SKIP LOCKED`` zwei Workern erlaubt, ``household.dissolved`` und ein
``member.left`` desselben Haushalts gleichzeitig zu ziehen. Dann wäre die Reihenfolge wieder offen.

Kalender- und Wearables-Handler bleiben an ``member.left``: sie sind mitglieds-gescopt, voneinander
unabhängig und reihenfolgefrei.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import scoped_session
from app.logging import get_logger
from app.modules.accounts.models import Membership
from app.modules.economy import api as economy_api
from app.modules.marketplace import api as marketplace_api
from app.modules.tasks import api as tasks_api

_HANDLER_NAME = "app.settle_household_dissolution"  # stabiler Idempotenz-Schlüssel


@dataclass(frozen=True)
class DissolutionSettlement:
    """Was die Auflösung bewegt hat — nur Zähler, nie Inhalte."""

    members: int = 0
    withdrawn: int = 0
    reverted: int = 0
    tasks_released: int = 0
    points_expired: int = 0


async def settle_household_dissolution(*, household_id: uuid.UUID) -> DissolutionSettlement:
    """Die drei Schritte über alle Mitglieder, in **einer** Transaktion.

    Idempotent: ein zweiter Lauf findet keine offenen Positionen, keine Zuweisungen und Saldo 0.
    """
    settlement = DissolutionSettlement()
    # Irgendein Mitglied als Identität der Session — die Fachtabellen sind haushalts-gescopt, die
    # Mitglieds-Identität spielt für sie keine Rolle. (Die mitglieds-gescopten Art.-9-Tabellen
    # räumt der `member.left`-Handler ab, nicht dieser hier.)
    async with scoped_session(household_id=household_id, user_id=household_id) as probe:
        member_ids = list(await probe.scalars(select(Membership.user_id).order_by(Membership.id)))
    if not member_ids:
        return settlement

    withdrawn = reverted = released = expired = 0
    async with scoped_session(household_id=household_id, user_id=member_ids[0]) as session:
        for member_id in member_ids:
            positions = await marketplace_api.release_positions_of(
                session, household_id=household_id, member_id=member_id
            )
            withdrawn += positions["withdrawn"]
            reverted += positions["reverted"]
        for member_id in member_ids:
            released += await tasks_api.release_assignments_of(
                session, household_id=household_id, member_id=member_id
            )
        for member_id in member_ids:
            expired += await economy_api.expire_member_balance(
                session, household_id=household_id, member_id=member_id
            )

    return DissolutionSettlement(
        members=len(member_ids),
        withdrawn=withdrawn,
        reverted=reverted,
        tasks_released=released,
        points_expired=expired,
    )


async def on_household_dissolved(event: EventEnvelope) -> None:
    settlement = await settle_household_dissolution(household_id=event.household_id)
    get_logger("household_dissolution").info(
        "household_dissolution_settled",
        members=settlement.members,
        withdrawn=settlement.withdrawn,
        reverted=settlement.reverted,
        tasks_released=settlement.tasks_released,
        points_expired=settlement.points_expired,
    )


def register_household_dissolution_handler(dispatcher: OutboxDispatcher) -> None:
    """Bindet den Ablauf. Einmal am Composition Root aufgerufen (Worker-Start)."""
    dispatcher.register("household.dissolved", _HANDLER_NAME, on_household_dissolved)
