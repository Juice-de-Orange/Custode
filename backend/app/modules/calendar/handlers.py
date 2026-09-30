"""Outbox-Handler: verlässt jemand den Haushalt, endet sein Kalender-Zugang (KONZEPT §5.1).

Zwei Dinge überleben eine Entfernung sonst, und eines davon ist ein Loch:

**Der ICS-Feed-Token.** ``GET /v1/calendar/feed/<token>.ics`` ist **unauthentifiziert** — das muss
er sein, weil Kalender-Apps keine Cookies schicken (ADR-0042). Die einzige Zugangskontrolle ist der
unratbare Token. Ein entferntes Mitglied behielt damit **dauerhaft** Lesezugriff auf den
Haushaltskalender: kein Cookie, keine Rolle, kein Ablauf, nichts, was der Entzug der Mitgliedschaft
berührt hätte. Der Feed lebt weiter, bis ihn jemand von Hand widerruft — und niemand tut das.

**CalDAV-Abos.** Sie gehören der Person (fremde URL, fremde Zugangsdaten) und spiegeln in den
Haushaltskalender. Bleiben sie stehen, holt der 15-Minuten-Cron weiter Termine aus dem privaten
Nextcloud einer Person, die nicht mehr dazugehört — in einen Haushalt, der sie nicht mehr angeht.

Registriert am Composition Root (``app.worker``), weil der Kernel keine Module importieren darf
(ADR-0039). Zustellung ist at-least-once, beide Schritte sind idempotent (ein zweiter Lauf findet
keine lebenden Zeilen mehr).

**Zwei Handler, nicht einer — und das ist der Punkt.** Bis 2026-08-01 liefen Feed-Widerruf und
Abo-Löschung in **einer** Transaktion unter **einem** Idempotenz-Schlüssel. Damit hing der Widerruf
des unauthentifizierten Feed-Tokens am Gelingen der Abo-Löschung: ein CalDAV-Abo mit einer
Besonderheit rollt die Feed-Entwertung mit zurück, und nach fünf Versuchen landet beides im DLQ —
der Feed bliebe **dauerhaft** offen. Der Feed-Widerruf ist die schärfere der beiden Zusagen (der
Token IST die Zugangskontrolle) und darf deshalb nicht an der schwächeren hängen. Eigener
Schlüssel, eigene Transaktion, eigener Retry-Zähler.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import scoped_session
from app.logging import get_logger
from app.modules.calendar import service
from app.modules.calendar.models import ExternalCalendarSubscription

# Stabile Idempotenz-Schlüssel — nie umbenennen. Der alte Name bleibt beim Abo-Handler, damit
# bereits verarbeitete Ereignisse nicht erneut laufen.
_SUBSCRIPTIONS_HANDLER = "calendar.revoke_on_member_left"
_FEED_HANDLER = "calendar.revoke_feed_on_member_left"


async def revoke_feed_on_member_left(event: EventEnvelope) -> None:
    """Nur den Feed-Token entwerten — in einer eigenen Transaktion.

    Getrennt vom Abo-Handler, weil der Token die einzige Zugangskontrolle einer
    unauthentifizierten Route ist. Er darf nicht mit einem CalDAV-Fehlschlag zurückgerollt werden.
    """
    raw_id = event.payload.get("user_id")
    if not raw_id:
        return
    member_id = uuid.UUID(raw_id)
    async with scoped_session(household_id=event.household_id, user_id=member_id) as session:
        await service.revoke_feed(session, member_id=member_id)


async def on_member_left(event: EventEnvelope) -> None:
    """Die CalDAV-Abos der Person stilllegen."""
    raw_id = event.payload.get("user_id")
    if not raw_id:
        return
    member_id = uuid.UUID(raw_id)

    # Mitglieds-gescopt öffnen: die Abo-Zeilen gehören der Person. Der Haushalt kommt aus dem
    # Ereignis, nicht aus einer Annahme.
    async with scoped_session(household_id=event.household_id, user_id=member_id) as session:
        subscriptions = (
            await session.scalars(
                select(ExternalCalendarSubscription).where(
                    ExternalCalendarSubscription.member_id == member_id,
                    ExternalCalendarSubscription.deleted_at.is_(None),
                )
            )
        ).all()
        for subscription in subscriptions:
            await service.delete_subscription(
                session,
                household_id=event.household_id,
                member_id=member_id,
                subscription_id=subscription.id,
            )

    # Nur Zähler — nie ein Token, nie eine URL (die trägt bei den üblichen Anbietern den
    # Fremdsystem-Benutzernamen im Pfad).
    get_logger("calendar").info("member_left_revoked", subscriptions=len(subscriptions))


def register_calendar_handlers(dispatcher: OutboxDispatcher) -> None:
    """Bindet den Widerruf. Einmal am Composition Root aufgerufen (Worker-Start)."""
    # Feed zuerst registriert: der Dispatcher arbeitet die Handler eines Ereignisses in
    # Registrierungsreihenfolge ab, und der Feed ist die schärfere Zusage.
    dispatcher.register("member.left", _FEED_HANDLER, revoke_feed_on_member_left)
    dispatcher.register("member.left", _SUBSCRIPTIONS_HANDLER, on_member_left)
