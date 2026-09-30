"""comments use-cases (KONZEPT §5.12). Runs on the request's RLS-scoped session. Comments are
generic: ``(object_type, object_id)`` reference any object without a cross-module FK. Online-first;
threads are listed oldest-first. @-Mentions + notification fan-out are later slices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.comments.models import Comment
from app.modules.comments.schemas import CommentCreate, CommentUpdate


async def create_comment(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, data: CommentCreate
) -> Comment:
    """Post a comment on an object; emits ``comment.created``."""
    comment = Comment(
        household_id=household_id,
        object_type=data.object_type,
        object_id=data.object_id,
        author_id=author_id,
        body_md=data.body_md,
    )
    session.add(comment)
    await emit(session, type="comment.created", household_id=household_id, payload={})
    await session.flush()
    return comment


async def list_comments(
    session: AsyncSession, *, object_type: str, object_id: uuid.UUID
) -> list[Comment]:
    """The thread on one object (RLS-scoped), oldest first."""
    rows = await session.scalars(
        select(Comment)
        .where(
            Comment.object_type == object_type,
            Comment.object_id == object_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.asc())
    )
    return list(rows)


async def update_comment(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    author_id: uuid.UUID,
    comment_id: uuid.UUID,
    expected_version: int,
    data: CommentUpdate,
) -> Comment:
    """Edit a comment's body under optimistic concurrency (``expected_version`` = If-Match). Only
    the author may edit it (others 403); 404 if gone; 412 if stale. RLS scopes to the household.
    Emits ``comment.updated``."""
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Kommentar nicht gefunden", status=404)
    if comment.author_id != author_id:
        raise ProblemException(slug="forbidden", title="Nicht dein Kommentar", status=403)
    if comment.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Kommentar zwischenzeitlich geändert", status=412
        )
    comment.body_md = data.body_md
    await emit(session, type="comment.updated", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(comment, attribute_names=["version", "updated_at"])
    return comment


async def delete_comment(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, comment_id: uuid.UUID
) -> None:
    """Soft-delete a comment. Only the author may delete it (others 403); 404 if gone. RLS scopes to
    the household. Emits ``comment.deleted``."""
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Kommentar nicht gefunden", status=404)
    if comment.author_id != author_id:
        raise ProblemException(slug="forbidden", title="Nicht dein Kommentar", status=403)
    comment.deleted_at = datetime.now(UTC)
    await emit(session, type="comment.deleted", household_id=household_id, payload={})
    await session.flush()


async def purge_for_object(
    session: AsyncSession, *, household_id: uuid.UUID, object_type: str, object_id: uuid.UUID
) -> int:
    """Soft-delete every (still-live) comment on one object — used by the reaper when the commented
    object is deleted (P7-S20). Keyed only on ``(object_type, object_id)``; ``comments`` never reads
    the foreign module. Idempotent: a re-run matches no live rows. Emits ``comment.deleted`` once if
    it removed anything. Returns the count removed."""
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Comment)
            .where(
                Comment.object_type == object_type,
                Comment.object_id == object_id,
                Comment.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        ),
    )
    removed = result.rowcount or 0
    if removed:
        await emit(session, type="comment.deleted", household_id=household_id, payload={})
        await session.flush()
    return removed
