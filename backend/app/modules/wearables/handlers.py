"""Outbox-Handler: verlässt jemand den Haushalt, gehen seine Gesundheitsdaten mit (Art. 9).

Die Wearable-Anbindung ist an das Paar (Haushalt, Mitglied) gebunden — Verbindung *und* Consent
(ADR-0081). Endet die Mitgliedschaft, endet die Rechtsgrundlage: die Einwilligung galt für diesen
Haushalt, und der Nacht-Cron würde sonst weiter Art.-9-Daten einer Person abholen, die nicht mehr
dazugehört, in eine Zeile, die sie niemandem mehr zugänglich macht.

Es wird **hart** gelöscht, nicht getombstoned: die Tabellen tragen ein
``CHECK (deleted_at IS NULL)`` (Migration 0069), weil Art. 9 ein Löschen verlangt, das wirklich
löscht. Der Consent-Ledger bleibt — er ist der Nachweis, dass eine Einwilligung bestand und endete,
und genau das muss auditierbar sein.

Registriert am Composition Root (ADR-0039). Zustellung at-least-once; ein zweiter Lauf findet keine
Verbindung mehr und tut nichts.
"""

from __future__ import annotations

import uuid

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import scoped_session
from app.logging import get_logger
from app.modules.wearables import service

_HANDLER_NAME = "wearables.disconnect_on_member_left"  # stabiler Schlüssel — nie umbenennen


async def on_member_left(event: EventEnvelope) -> None:
    """Jede Wearable-Verbindung der Person in diesem Haushalt trennen und ihre Daten löschen."""
    raw_id = event.payload.get("user_id")
    if not raw_id:
        return
    member_id = uuid.UUID(raw_id)

    # Mitglieds-gescopt öffnen — die RLS auf diesen Tabellen trägt ``member_id`` im Prädikat
    # (ADR-0081). Ohne den richtigen ``app.user_id`` sähe der Handler schlicht null Zeilen und
    # täte still nichts: die schlimmere Variante, weil nichts fehlschlägt.
    async with scoped_session(household_id=event.household_id, user_id=member_id) as session:
        connections = await service.list_connections(session, member_id=member_id)
        for connection in connections:
            await service.delete_connection(
                session,
                household_id=event.household_id,
                member_id=member_id,
                connection_id=connection.id,
            )

    # Nur die Anzahl — nie ein Provider-Token, nie ein Messwert.
    get_logger("wearables").info("member_left_disconnected", connections=len(connections))


def register_wearables_handlers(dispatcher: OutboxDispatcher) -> None:
    """Bindet die Trennung. Einmal am Composition Root aufgerufen (Worker-Start)."""
    dispatcher.register("member.left", _HANDLER_NAME, on_member_left)
