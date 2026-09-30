"""Outbox event handlers, wired by the registry (``registry.py``).

The invalidation bridge turns a delivered domain event into a per-household SSE
invalidation hint (ARCHITECTURE §7, ADR-002): the hint names the client-cache entity that
changed; the client refetches via the normal authorized API, so the hint carries no payload.

Publishing is best-effort (``pubsub`` swallows Redis failures), so the handler always
succeeds and never dead-letters on a transient Redis blip — the DB change is already durable.
Registered under the stable name ``invalidation_bridge`` (the idempotency-ledger key — keep
it stable across deploys)."""

from __future__ import annotations

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.events.pubsub import publish_hint
from app.kernel.http.sse import InvalidationHint

_HANDLER_NAME = "invalidation_bridge"

# Domain event type -> the client-cache entity it invalidates. Unmapped types are ignored
# (no hint). Add a row when a new event should nudge a client query.
_ENTITY_BY_TYPE: dict[str, str] = {
    "member.joined": "members",
    "member.left": "members",
    "member.role_changed": "members",
    "recipe.created": "recipes",
    "recipe.updated": "recipes",
    "recipe.deleted": "recipes",
    "shopping.changed": "shopping",
    "task.created": "tasks",
    "task.updated": "tasks",
    "task.deleted": "tasks",
    "task_instance.created": "tasks",
    "task.completed": "tasks",
    "reward.changed": "rewards",
    "reward.redeemed": "rewards",
    "thanks.sent": "economy",
    "market.listing.created": "marketplace",
    "market.listing.sold": "marketplace",
    "market.trade.settled": "marketplace",
    "market.trade.reverted": "marketplace",
    "market.changed": "marketplace",
    "capture.created": "capture",
    "capture.processed": "capture",
    "calendar.event.created": "calendar",
    "calendar.event.updated": "calendar",
    "calendar.event.deleted": "calendar",
    "calendar.subscription.created": "calendar",
    "calendar.subscription.updated": "calendar",
    "calendar.subscription.deleted": "calendar",
    "mealplan.updated": "mealplan",
    "mealplan.cooked": "recipes",  # cooking a planned recipe bumps its "last cooked" history
    "note.created": "notes",
    "note.updated": "notes",
    "note.deleted": "notes",
    "letter.created": "letters",
    "letter.read": "letters",
    "guide.created": "guides",
    "guide.updated": "guides",
    "guide.deleted": "guides",
    "comment.created": "comments",
    "comment.updated": "comments",
    "comment.deleted": "comments",
    "link.created": "links",
    "link.deleted": "links",
    "vault.item_changed": "vault",
    "vault.key_changed": "vault",
    "feedback.created": "feedback",
}


async def invalidation_bridge(event: EventEnvelope) -> None:
    """Publish an invalidation hint for events that change client-visible state."""
    entity = _ENTITY_BY_TYPE.get(event.type)
    if entity is None:
        return
    hint = InvalidationHint(entity=entity, id=str(event.household_id), version=event.version)
    await publish_hint(event.household_id, hint)


def register_handlers(dispatcher: OutboxDispatcher) -> None:
    """Bind every kernel handler to its event types. Called once by the registry."""
    for event_type in _ENTITY_BY_TYPE:
        dispatcher.register(event_type, _HANDLER_NAME, invalidation_bridge)
