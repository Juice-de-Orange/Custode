"""HTTP layer for ``guides`` (KONZEPT §5). Anleitungen — household-scoped (RLS), online-first with
PATCH + If-Match (ETag = version). Reads (incl. German FTS) are any member; writes member/admin."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.storage import get_storage
from app.modules.guides import service
from app.modules.guides.models import Guide, GuideAttachment
from app.modules.guides.schemas import (
    AttachmentResponse,
    GuideCreate,
    GuideResponse,
    GuideSummary,
    GuideUpdate,
)

guides_router = APIRouter(prefix="/v1/guides", tags=["guides"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]

# Attachments may be documents (PDF/images/…), so a more generous cap than recipe photos.
_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MiB


def _sanitize_filename(name: str | None) -> str:
    """A safe, length-capped filename: strip path + control chars (header-injection / traversal)."""
    base = (name or "datei").replace("\\", "/").split("/")[-1]
    cleaned = "".join(c for c in base if c.isprintable() and c not in '"\r\n').strip()
    return (cleaned or "datei")[:255]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _response(guide: Guide) -> GuideResponse:
    return GuideResponse(
        id=guide.id,
        title=guide.title,
        body_md=guide.body_md,
        category=guide.category,
        tags=list(guide.tags),
        contact_id=guide.contact_id,
        author_id=guide.author_id,
        created_at=guide.created_at,
        updated_at=guide.updated_at,
    )


@guides_router.get("")
async def list_guides(
    principal: CurrentPrincipal,
    session: ScopedSession,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> list[GuideSummary]:
    """The household's guides. ``?q=`` runs a German FTS (ranked); ``?category=`` filters."""
    _require_household(principal)
    guides = await service.list_guides(session, q=q, category=category)
    return [
        GuideSummary(
            id=g.id,
            title=g.title,
            category=g.category,
            tags=list(g.tags),
            contact_id=g.contact_id,
            updated_at=g.updated_at,
        )
        for g in guides
    ]


@guides_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_guide(
    payload: GuideCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> GuideResponse:
    household_id = _require_household(principal)
    guide = await service.create_guide(
        session, household_id=household_id, author_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{guide.version}"'
    return _response(guide)


@guides_router.get("/{guide_id}")
async def get_guide(
    guide_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> GuideResponse:
    _require_household(principal)
    guide = await service.get_guide(session, guide_id=guide_id)
    response.headers["ETag"] = f'"{guide.version}"'
    return _response(guide)


@guides_router.patch("/{guide_id}", dependencies=[Depends(require_csrf)])
async def update_guide(
    guide_id: uuid.UUID,
    payload: GuideUpdate,
    request: Request,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> GuideResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    guide = await service.update_guide(
        session,
        household_id=household_id,
        guide_id=guide_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{guide.version}"'
    return _response(guide)


@guides_router.delete(
    "/{guide_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_guide(
    guide_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_guide(session, household_id=household_id, guide_id=guide_id)


# --- Attachments (KONZEPT §5, P7-S22) ------------------------------------------------------------


def _attachment_response(attachment: GuideAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        guide_id=attachment.guide_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        byte_size=attachment.byte_size,
        uploaded_by=attachment.uploaded_by,
        created_at=attachment.created_at,
    )


@guides_router.get("/{guide_id}/attachments")
async def list_attachments(
    guide_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> list[AttachmentResponse]:
    """A guide's attachments (metadata only; oldest first)."""
    _require_household(principal)
    attachments = await service.list_attachments(session, guide_id=guide_id)
    return [_attachment_response(a) for a in attachments]


@guides_router.post(
    "/{guide_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def upload_attachment(
    guide_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    file: UploadFile,
) -> AttachmentResponse:
    """Attach a file to a guide. 503 if no storage backend is configured (Graceful Enhancement),
    413 if it exceeds the size cap. The bytes go to blob storage; only metadata is persisted."""
    household_id = _require_household(principal)
    if not get_storage().enabled:
        raise ProblemException(
            slug="storage_unavailable", title="Datei-Upload nicht verfügbar", status=503
        )
    raw = await file.read(_MAX_ATTACHMENT_BYTES + 1)
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raise ProblemException(slug="file_too_large", title="Datei zu groß", status=413)
    attachment = await service.add_attachment(
        session,
        household_id=household_id,
        guide_id=guide_id,
        uploaded_by=principal.user_id,
        filename=_sanitize_filename(file.filename),
        content_type=file.content_type or "application/octet-stream",
        data=raw,
    )
    return _attachment_response(attachment)


@guides_router.get("/{guide_id}/attachments/{attachment_id}")
async def download_attachment(
    guide_id: uuid.UUID,
    attachment_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
) -> Response:
    """Stream an attachment's bytes to a household member; 404 if it or its blob is gone."""
    _require_household(principal)
    attachment = await service.get_attachment(session, attachment_id=attachment_id)
    data = service.read_attachment_bytes(attachment)
    if data is None:
        raise ProblemException(slug="not_found", title="Anhang nicht gefunden", status=404)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@guides_router.delete(
    "/{guide_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_attachment(
    guide_id: uuid.UUID,
    attachment_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
) -> None:
    household_id = _require_household(principal)
    await service.delete_attachment(session, household_id=household_id, attachment_id=attachment_id)
