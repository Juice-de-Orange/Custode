"""HTTP layer for ``comments`` (KONZEPT §5.12). Generic comments on any object — household-scoped
(RLS), online-first. Reads are any member; posting/editing/deleting is member/admin with CSRF (own
only). Edits use PATCH + If-Match (``version`` = ETag, carried inline in each thread entry)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.comments import service
from app.modules.comments.models import Comment
from app.modules.comments.schemas import CommentCreate, CommentResponse, CommentUpdate

comments_router = APIRouter(prefix="/v1/comments", tags=["comments"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _response(comment: Comment) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        object_type=comment.object_type,
        object_id=comment.object_id,
        author_id=comment.author_id,
        body_md=comment.body_md,
        version=comment.version,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@comments_router.get("")
async def list_comments(
    principal: CurrentPrincipal,
    session: ScopedSession,
    object_type: Annotated[str, Query()],
    object_id: Annotated[uuid.UUID, Query()],
) -> list[CommentResponse]:
    """The comment thread on one object (oldest first)."""
    _require_household(principal)
    comments = await service.list_comments(session, object_type=object_type, object_id=object_id)
    return [_response(c) for c in comments]


@comments_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_comment(
    payload: CommentCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> CommentResponse:
    """Post a comment on an object."""
    household_id = _require_household(principal)
    comment = await service.create_comment(
        session, household_id=household_id, author_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{comment.version}"'
    return _response(comment)


@comments_router.patch("/{comment_id}", dependencies=[Depends(require_csrf)])
async def update_comment(
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    request: Request,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> CommentResponse:
    """Edit one of your own comments (403 if not yours, 404 if gone, 412 if stale). If-Match."""
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    comment = await service.update_comment(
        session,
        household_id=household_id,
        author_id=principal.user_id,
        comment_id=comment_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{comment.version}"'
    return _response(comment)


@comments_router.delete(
    "/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_comment(
    comment_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> None:
    """Soft-delete one of your own comments (403 if it isn't yours, 404 if gone)."""
    household_id = _require_household(principal)
    await service.delete_comment(
        session, household_id=household_id, author_id=principal.user_id, comment_id=comment_id
    )
