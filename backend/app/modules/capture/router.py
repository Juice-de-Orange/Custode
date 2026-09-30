"""HTTP layer for ``capture`` (KONZEPT §5.17). Thin: validate -> service -> response. Captures are
household-scoped (RLS) and per-member (the inbox shows only your own). Triage is for adults/members
— children are excluded in S9a (confirm creates items/tasks; a child-safe Zuruf is a later
extension)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.ports.llm import LlmPort, get_llm
from app.modules.capture import service
from app.modules.capture.models import Capture
from app.modules.capture.schemas import CaptureCreate, CaptureResponse, ParsedProposal

capture_router = APIRouter(prefix="/v1/capture", tags=["capture"])

# Quick-Capture triage is admin/member only — children are excluded in S9a.
CapturePrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _capture_response(capture: Capture) -> CaptureResponse:
    return CaptureResponse(
        id=capture.id,
        raw_text=capture.raw_text,
        status=capture.status,
        tags=list(capture.tags),
        proposal=ParsedProposal.model_validate(capture.proposal_json),
        created_at=capture.created_at,
    )


@capture_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_capture(
    payload: CaptureCreate,
    principal: CapturePrincipal,
    session: ScopedSession,
    llm: Annotated[LlmPort, Depends(get_llm)],
) -> CaptureResponse:
    """Zuruf: parse a free-text line into a proposal and drop it into the inbox."""
    household_id = _require_household(principal)
    capture = await service.create_capture(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        raw_text=payload.raw_text,
        llm=llm,
    )
    return _capture_response(capture)


@capture_router.get("/inbox")
async def list_inbox(principal: CapturePrincipal, session: ScopedSession) -> list[CaptureResponse]:
    """The caller's own open captures awaiting triage."""
    _require_household(principal)
    captures = await service.list_inbox(session, member_id=principal.user_id)
    return [_capture_response(c) for c in captures]


@capture_router.post("/{capture_id}/confirm", dependencies=[Depends(require_csrf)])
async def confirm_capture(
    capture_id: uuid.UUID, principal: CapturePrincipal, session: ScopedSession
) -> CaptureResponse:
    """Apply the proposal — create the shopping item / personal task — and mark it confirmed."""
    household_id = _require_household(principal)
    capture = await service.confirm_capture(
        session, household_id=household_id, member_id=principal.user_id, capture_id=capture_id
    )
    return _capture_response(capture)


@capture_router.post("/{capture_id}/dismiss", dependencies=[Depends(require_csrf)])
async def dismiss_capture(
    capture_id: uuid.UUID, principal: CapturePrincipal, session: ScopedSession
) -> CaptureResponse:
    """Discard a proposed capture."""
    _require_household(principal)
    capture = await service.dismiss_capture(
        session, member_id=principal.user_id, capture_id=capture_id
    )
    return _capture_response(capture)
