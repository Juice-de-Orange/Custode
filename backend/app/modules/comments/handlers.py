"""Outbox handler that reaps a deleted object's comments (KONZEPT §5.12, P7-S20).

Comments reference their target only by the ``(object_type, object_id)`` discriminator — there is no
cross-module FK, so a deleted recipe/note/guide would otherwise leave **orphaned** comment rows. The
handler subscribes to the relevant ``*.deleted`` events and soft-deletes the matching comments via
the module's own service. The event is matched **by name only** (a string map below); comments never
import the foreign module, so the import-linter boundary holds.

Because ``kernel`` must not import ``modules``, it is **registered at the app composition root**
(``app.worker``), not in the kernel. The handler opens its own household-scoped session; delivery is
at-least-once and the purge is idempotent (a re-run matches no live rows), so re-delivery is safe.
"""

from __future__ import annotations

import uuid

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.tenancy.session import scoped_session
from app.modules.comments import service

_HANDLER_NAME = "comments.purge_on_object_deleted"  # stable idempotency-ledger key — never rename

# Deletion events whose object can carry comments, mapped to the comment ``object_type`` + the
# payload key holding the deleted id. ``task`` is intentionally absent: ``task.deleted`` is a
# *template* event, while comment ``task`` endpoints reference task *instances* (no instance-delete
# event exists yet) — a future slice handles that without changing this map's contract.
_OBJECT_BY_EVENT: dict[str, tuple[str, str]] = {
    "recipe.deleted": ("recipe", "recipe_id"),
    "note.deleted": ("note", "note_id"),
    "guide.deleted": ("guide", "guide_id"),
}


async def on_object_deleted(event: EventEnvelope) -> None:
    """Soft-delete the comments on whichever object this ``*.deleted`` event reaped."""
    mapping = _OBJECT_BY_EVENT.get(event.type)
    if mapping is None:
        return
    object_type, id_key = mapping
    raw_id = event.payload.get(id_key)
    if not raw_id:
        return
    # comments RLS only needs household_id; a nil user keeps the GUC cast valid (no PII needed).
    async with scoped_session(
        household_id=event.household_id, user_id="00000000-0000-0000-0000-000000000000"
    ) as session:
        await service.purge_for_object(
            session,
            household_id=event.household_id,
            object_type=object_type,
            object_id=uuid.UUID(raw_id),
        )


def register_comments_handlers(dispatcher: OutboxDispatcher) -> None:
    """Bind the comment reaper. Called once at the app composition root (worker startup)."""
    for event_type in _OBJECT_BY_EVENT:
        dispatcher.register(event_type, _HANDLER_NAME, on_object_deleted)
