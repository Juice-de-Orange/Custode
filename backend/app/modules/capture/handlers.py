"""Outbox event handler for capture's action chains (KONZEPT §5.17, ADR-0039).

This is the **first module-provided** outbox handler with a DB side effect. It reacts to shopping's
item-granular ``shopping.item.checked`` and activates the armed follow-up task (Deo-Fall) via the
public ``tasks.api`` — never touching internals. Because ``kernel`` must not import ``modules``, it
is **registered at the app composition root** (``app.worker``), not in the kernel registry
(ADR-0039). The handler opens its own household-scoped session (the dispatcher only hands it the
envelope); delivery is at-least-once and activation is idempotent, so re-delivery is harmless."""

from __future__ import annotations

import uuid

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import scoped_session
from app.modules.tasks import api as tasks_api

_HANDLER_NAME = "capture.activate_on_item_checked"  # stable idempotency-ledger key — never rename


async def on_shopping_item_checked(event: EventEnvelope) -> None:
    """Activate any task armed on this shopping item (``armed -> open``)."""
    item_id = event.payload.get("id")
    # The checker scopes the session; task_instances RLS only needs household_id, so a nil user is
    # acceptable. Fall back to nil if the event somehow lacks it (keeps the GUC cast valid).
    user_id = event.payload.get("user_id") or "00000000-0000-0000-0000-000000000000"
    if not item_id:
        return
    async with scoped_session(household_id=event.household_id, user_id=user_id) as session:
        await tasks_api.activate_on_item_checked(
            session, household_id=event.household_id, item_id=uuid.UUID(item_id)
        )


def register_capture_handlers(dispatcher: OutboxDispatcher) -> None:
    """Bind capture's handlers. Called once at the app composition root (worker startup)."""
    dispatcher.register("shopping.item.checked", _HANDLER_NAME, on_shopping_item_checked)
