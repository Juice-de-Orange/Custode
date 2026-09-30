"""HTTP layer for ``messaging`` (KONZEPT §5.12). „Briefe" — household-scoped, online-first. Reads
are any member; sending is member/admin with CSRF. Fetching a letter marks it read."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.messaging import service
from app.modules.messaging.models import Letter
from app.modules.messaging.schemas import (
    LetterCreate,
    LetterResponse,
    LetterSummary,
    LetterToTaskResult,
    UnreadCount,
)

letters_router = APIRouter(prefix="/v1/letters", tags=["messaging"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _summary(letter: Letter, read_by_me: bool, read_count: int) -> LetterSummary:
    return LetterSummary(
        id=letter.id,
        subject=letter.subject,
        from_id=letter.from_id,
        to_ids=list(letter.to_ids),
        created_at=letter.created_at,
        read_by_me=read_by_me,
        read_count=read_count,
    )


@letters_router.get("")
async def list_inbox(principal: CurrentPrincipal, session: ScopedSession) -> list[LetterSummary]:
    """The viewer's letters (received + sent), newest first, with read flags."""
    _require_household(principal)
    rows = await service.list_inbox(session, viewer_id=principal.user_id)
    return [_summary(letter, read_by_me, count) for letter, read_by_me, count in rows]


@letters_router.get("/unread-count")
async def unread_count(principal: CurrentPrincipal, session: ScopedSession) -> UnreadCount:
    """How many letters addressed to the viewer are still unread."""
    _require_household(principal)
    return UnreadCount(unread=await service.unread_count(session, viewer_id=principal.user_id))


@letters_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_letter(
    payload: LetterCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> LetterResponse:
    """Send a letter (``to_ids`` empty = round-letter to the whole household)."""
    household_id = _require_household(principal)
    letter = await service.create_letter(
        session, household_id=household_id, from_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{letter.version}"'
    return LetterResponse(
        id=letter.id,
        subject=letter.subject,
        body_md=letter.body_md,
        from_id=letter.from_id,
        to_ids=list(letter.to_ids),
        created_at=letter.created_at,
        read_by_me=False,
        read_count=0,
    )


@letters_router.get("/{letter_id}")
async def get_letter(
    letter_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> LetterResponse:
    """One letter; fetching it marks it read for the viewer (if a recipient). 404 if gone."""
    _require_household(principal)
    letter, read_by_me, read_count = await service.get_letter(
        session, viewer_id=principal.user_id, letter_id=letter_id
    )
    return LetterResponse(
        id=letter.id,
        subject=letter.subject,
        body_md=letter.body_md,
        from_id=letter.from_id,
        to_ids=list(letter.to_ids),
        created_at=letter.created_at,
        read_by_me=read_by_me,
        read_count=read_count,
    )


@letters_router.post(
    "/{letter_id}/to-task",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def convert_to_task(
    letter_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> LetterToTaskResult:
    """„Kümmerst du dich?": create a personal task from a letter (P7-S5); the letter stays."""
    household_id = _require_household(principal)
    task_id, title = await service.convert_to_task(
        session, household_id=household_id, letter_id=letter_id, author_id=principal.user_id
    )
    return LetterToTaskResult(task_id=task_id, title=title)
