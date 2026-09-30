"""messaging use-cases (KONZEPT §5.12). Runs on the request's RLS-scoped session. „Briefe" are
household-scoped; a letter with empty ``to_ids`` is a round-letter to everyone. Read receipts live
in ``letter_reads`` (one row per letter+reader; ADR-0062). Online-first; no Sync-Batch."""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.messaging.models import Letter, LetterRead
from app.modules.messaging.schemas import LetterCreate
from app.modules.tasks import api as tasks_api


def _addressed_to(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """SQL predicate: the viewer is an intended recipient (round-letter or named in ``to_ids``)."""
    return or_(func.cardinality(Letter.to_ids) == 0, Letter.to_ids.contains([viewer_id]))


async def create_letter(
    session: AsyncSession, *, household_id: uuid.UUID, from_id: uuid.UUID, data: LetterCreate
) -> Letter:
    """Send a letter; emits ``letter.created``."""
    letter = Letter(
        household_id=household_id,
        from_id=from_id,
        to_ids=list(data.to_ids),
        subject=data.subject,
        body_md=data.body_md,
    )
    session.add(letter)
    await emit(session, type="letter.created", household_id=household_id, payload={})
    await session.flush()
    return letter


async def _read_maps(
    session: AsyncSession, letter_ids: list[uuid.UUID], viewer_id: uuid.UUID
) -> tuple[dict[uuid.UUID, int], set[uuid.UUID]]:
    """``(read_count_by_letter, letters_read_by_viewer)`` for the given letters."""
    if not letter_ids:
        return {}, set()
    counts = await session.execute(
        select(LetterRead.letter_id, func.count())
        .where(LetterRead.letter_id.in_(letter_ids))
        .group_by(LetterRead.letter_id)
    )
    count_by: dict[uuid.UUID, int] = {}
    for row in counts.all():
        count_by[row[0]] = row[1]
    mine = await session.scalars(
        select(LetterRead.letter_id).where(
            LetterRead.letter_id.in_(letter_ids), LetterRead.user_id == viewer_id
        )
    )
    return count_by, set(mine)


async def list_inbox(
    session: AsyncSession, *, viewer_id: uuid.UUID
) -> list[tuple[Letter, bool, int]]:
    """The viewer's letters (received round-letters/addressed + sent by them), newest first, each
    with ``(read_by_me, read_count)``. RLS already scopes to the household."""
    letters = list(
        await session.scalars(
            select(Letter)
            .where(
                Letter.deleted_at.is_(None),
                or_(Letter.from_id == viewer_id, _addressed_to(viewer_id)),
            )
            .order_by(Letter.created_at.desc())
        )
    )
    count_by, mine = await _read_maps(session, [letter.id for letter in letters], viewer_id)
    return [(letter, letter.id in mine, count_by.get(letter.id, 0)) for letter in letters]


async def get_letter(
    session: AsyncSession, *, viewer_id: uuid.UUID, letter_id: uuid.UUID
) -> tuple[Letter, bool, int]:
    """One letter (RLS hides other households -> 404). Marks it read for the viewer if they are a
    recipient and not the author. Returns ``(letter, read_by_me, read_count)``."""
    letter = await session.get(Letter, letter_id)
    if letter is None or letter.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Brief nicht gefunden", status=404)
    is_recipient = letter.from_id != viewer_id and (not letter.to_ids or viewer_id in letter.to_ids)
    if is_recipient:
        await session.execute(
            pg_insert(LetterRead)
            .values(household_id=letter.household_id, letter_id=letter.id, user_id=viewer_id)
            .on_conflict_do_nothing(index_elements=["letter_id", "user_id"])
        )
        await emit(
            session,
            type="letter.read",
            household_id=letter.household_id,
            payload={"letter_id": str(letter.id)},
        )
        await session.flush()
    count_by, mine = await _read_maps(session, [letter.id], viewer_id)
    return letter, letter.id in mine, count_by.get(letter.id, 0)


async def convert_to_task(
    session: AsyncSession, *, household_id: uuid.UUID, letter_id: uuid.UUID, author_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    """„Kümmerst du dich?" (P7-S5, ADR-0063): create a personal task from a letter, assigned to the
    caller, via ``tasks.api.create_personal_task`` (points 0, one-way). The letter's subject becomes
    the task title; the letter stays (non-destructive). Returns ``(task_id, title)``."""
    letter = await session.get(Letter, letter_id)
    if letter is None or letter.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Brief nicht gefunden", status=404)
    task = await tasks_api.create_personal_task(
        session, household_id=household_id, title=letter.subject, assigned_to=author_id
    )
    return task.id, letter.subject


async def unread_count(session: AsyncSession, *, viewer_id: uuid.UUID) -> int:
    """How many letters addressed to the viewer (and not authored by them) are still unread."""
    read_subq = select(LetterRead.letter_id).where(LetterRead.user_id == viewer_id)
    return (
        await session.scalar(
            select(func.count())
            .select_from(Letter)
            .where(
                Letter.deleted_at.is_(None),
                Letter.from_id != viewer_id,
                _addressed_to(viewer_id),
                Letter.id.not_in(read_subq),
            )
        )
    ) or 0
