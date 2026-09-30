"""HTTP layer for ``feedback`` (Roadmap Phase 8, „Feedback-Kanal"). Thin: validate -> service ->
response. Household-scoped (RLS). Submitting + listing one's own feedback is any member/admin (CSRF
on the write); the ops console (P8-S8) reads aggregates separately, never this fact table."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.feedback import service
from app.modules.feedback.models import Feedback
from app.modules.feedback.schemas import FeedbackCategory, FeedbackCreate, FeedbackResponse

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _response(item: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=item.id,
        # DB column is a plain str; it only ever holds a validated FeedbackCategory (set on write).
        category=cast(FeedbackCategory, item.category),
        message=item.message,
        error_ref=item.error_ref,
        route=item.route,
        created_at=item.created_at,
    )


@feedback_router.get("")
async def list_feedback(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[FeedbackResponse]:
    """The caller's own feedback submissions, newest first."""
    _require_household(principal)
    items = await service.list_own_feedback(session, author_id=principal.user_id)
    return [_response(i) for i in items]


@feedback_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_feedback(
    payload: FeedbackCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
) -> FeedbackResponse:
    """Submit feedback (bug/idea/praise/other) with an optional error-reference short-code."""
    household_id = _require_household(principal)
    item = await service.create_feedback(
        session, household_id=household_id, author_id=principal.user_id, data=payload
    )
    return _response(item)
