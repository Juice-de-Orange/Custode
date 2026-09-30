"""HTTP layer for ``links`` (KONZEPT §5.12 / Phase 7). Typed links between arbitrary objects —
household-scoped (RLS), online-first. Reads are any member; linking/unlinking is member/admin with
CSRF."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.links import service
from app.modules.links.models import ObjectLink
from app.modules.links.schemas import LinkCreate, LinkResponse

links_router = APIRouter(prefix="/v1/links", tags=["links"])

EditorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _response(link: ObjectLink) -> LinkResponse:
    return LinkResponse(
        id=link.id,
        src_type=link.src_type,
        src_id=link.src_id,
        dst_type=link.dst_type,
        dst_id=link.dst_id,
        relation=link.relation,
        created_at=link.created_at,
    )


@links_router.get("")
async def list_links(
    principal: CurrentPrincipal,
    session: ScopedSession,
    object_type: Annotated[str, Query()],
    object_id: Annotated[uuid.UUID, Query()],
) -> list[LinkResponse]:
    """Every link touching one object (oldest first)."""
    _require_household(principal)
    links = await service.list_links(session, object_type=object_type, object_id=object_id)
    return [_response(link) for link in links]


@links_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_link(
    payload: LinkCreate, principal: EditorPrincipal, session: ScopedSession
) -> LinkResponse:
    """Link two objects (idempotent, direction-independent)."""
    household_id = _require_household(principal)
    link = await service.create_link(
        session, household_id=household_id, created_by=principal.user_id, data=payload
    )
    return _response(link)


@links_router.delete(
    "/{link_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_link(
    link_id: uuid.UUID, principal: EditorPrincipal, session: ScopedSession
) -> None:
    """Remove a link (any household member; 404 if gone)."""
    household_id = _require_household(principal)
    await service.delete_link(session, household_id=household_id, link_id=link_id)
