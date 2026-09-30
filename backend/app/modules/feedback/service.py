"""feedback use-cases (Roadmap Phase 8, „Feedback-Kanal"). Runs on the request's RLS-scoped session.
The message is user content — it is persisted but never logged (no PII in logs, root CLAUDE.md)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.modules.feedback.models import Feedback
from app.modules.feedback.schemas import FeedbackCreate


async def create_feedback(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, data: FeedbackCreate
) -> Feedback:
    """Store a feedback submission; emits ``feedback.created`` (ops console consumes it later)."""
    item = Feedback(
        household_id=household_id,
        author_id=author_id,
        category=data.category,
        message=data.message,
        error_ref=data.error_ref,
        route=data.route,
        # Opt-in technical breadcrumbs only (no content) — stored as-is, never logged.
        diagnostics=data.diagnostics.model_dump() if data.diagnostics else None,
    )
    session.add(item)
    # Flush first so the server-side uuidv7 id is populated, then carry it in the event so the
    # (optional) issue-tracker forwarder can re-read the row (ADR-0076). Same transaction as the
    # insert -> transactional outbox intact. The message itself is NOT in the payload (no PII in the
    # outbox beyond the id); the forwarder loads the row under RLS.
    await session.flush()
    await emit(
        session, type="feedback.created", household_id=household_id, payload={"id": str(item.id)}
    )
    return item


async def get_feedback(session: AsyncSession, *, feedback_id: uuid.UUID) -> Feedback | None:
    """Load one submission by id (RLS scopes it to the session's household; excludes soft-deleted).
    Used by the composition-root forwarding handler (ADR-0076)."""
    rows = await session.scalars(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.deleted_at.is_(None))
    )
    return rows.first()


async def list_own_feedback(session: AsyncSession, *, author_id: uuid.UUID) -> list[Feedback]:
    """The caller's own feedback submissions, newest first (RLS scopes to the household; the
    ``author_id`` filter narrows to this member's own entries)."""
    rows = await session.scalars(
        select(Feedback)
        .where(Feedback.author_id == author_id, Feedback.deleted_at.is_(None))
        .order_by(Feedback.created_at.desc())
    )
    return list(rows)
