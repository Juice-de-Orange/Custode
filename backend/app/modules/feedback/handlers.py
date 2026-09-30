"""Outbox handler that best-effort forwards a new feedback submission to an external issue tracker
(ADR-0076, Roadmap Phase 8 — „Feedback → Issues"). Subscribes to ``feedback.created``; loads the row
under its household's RLS scope, maps it to an issue (pure ``build_issue``) and hands it to the
injected ``IssueTrackerPort``. The Null adapter makes this a no-op (inert by default).

Because ``kernel`` must not import ``modules``/``adapters``, the handler is registered at the app
composition root (``app/worker.py``) with the tracker chosen there via ``build_issue_tracker``. The
handler opens its own household-scoped session; delivery is at-least-once, so re-delivery may open a
duplicate issue — acceptable for best-effort triage. Forwarding must NEVER raise into the worker: a
failure degrades to a logged warning (failure class only, never the message — no PII)."""

from __future__ import annotations

import uuid

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from app.kernel.ports.issues import IssueTrackerPort
from app.kernel.tenancy.session import scoped_session
from app.logging import get_logger
from app.modules.feedback import service
from app.modules.feedback.forward import IssueDraft, build_issue

_HANDLER_NAME = "feedback.forward_to_issue_tracker"  # stable idempotency-ledger key — never rename
_NIL_USER = (
    "00000000-0000-0000-0000-000000000000"  # RLS needs only household_id; nil user for the GUC
)

_log = get_logger("feedback.forward")


async def _forward_draft(tracker: IssueTrackerPort, draft: IssueDraft) -> None:
    """Push one draft through the tracker; swallow any failure (best-effort, no PII in logs)."""
    try:
        await tracker.forward(title=draft.title, body=draft.body, labels=draft.labels)
    except Exception as exc:  # a graceful adapter returns False, but never let the worker break
        _log.warning("feedback_forward_error", error=type(exc).__name__)


async def on_feedback_created(event: EventEnvelope, tracker: IssueTrackerPort) -> None:
    raw_id = event.payload.get("id")
    if not raw_id:
        return  # pre-ADR-0076 events carried no id — nothing to load/forward
    async with scoped_session(household_id=event.household_id, user_id=_NIL_USER) as session:
        feedback = await service.get_feedback(session, feedback_id=uuid.UUID(raw_id))
        if feedback is None:
            return
        draft = build_issue(feedback)  # build while attached (attributes expire after the session)
    await _forward_draft(tracker, draft)


def register_feedback_handlers(dispatcher: OutboxDispatcher, tracker: IssueTrackerPort) -> None:
    """Bind the feedback forwarder. Called once at the app composition root (worker startup) with
    the tracker selected from settings — Null when unconfigured, so this is inert by default."""

    async def handler(event: EventEnvelope) -> None:
        await on_feedback_created(event, tracker)

    dispatcher.register("feedback.created", _HANDLER_NAME, handler)
