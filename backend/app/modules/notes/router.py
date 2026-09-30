"""HTTP layer for ``notes`` (KONZEPT §5 / Phase 7). Thin: validate -> service -> response. Notes are
household-scoped (RLS) with PATCH + If-Match (ADR-0029); GET/PATCH/POST carry an ETag (= version).
Reads are any household member; writes are member/admin with CSRF."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.notes import service
from app.modules.notes.models import Note
from app.modules.notes.schemas import (
    NoteCreate,
    NoteResponse,
    NoteSummary,
    NoteUpdate,
    NoteVersionResponse,
    ToTaskResult,
    TrashedNote,
)

notes_router = APIRouter(prefix="/v1/notes", tags=["notes"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _response(note: Note) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        title=note.title,
        body_md=note.body_md,
        pinned=note.pinned,
        author_id=note.author_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@notes_router.get("")
async def list_notes(
    principal: CurrentPrincipal,
    session: ScopedSession,
    pinned: Annotated[bool, Query()] = False,
) -> list[NoteSummary]:
    """The household's notes (pinned first). ``?pinned=true`` returns only the pinned ones."""
    _require_household(principal)
    notes = await service.list_notes(session, pinned_only=pinned)
    return [
        NoteSummary(
            id=n.id,
            title=n.title,
            pinned=n.pinned,
            author_id=n.author_id,
            updated_at=n.updated_at,
        )
        for n in notes
    ]


@notes_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_note(
    payload: NoteCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> NoteResponse:
    household_id = _require_household(principal)
    note = await service.create_note(
        session, household_id=household_id, author_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{note.version}"'
    return _response(note)


@notes_router.get("/trash")
async def list_trash(principal: CurrentPrincipal, session: ScopedSession) -> list[TrashedNote]:
    """The household's trashed (soft-deleted) notes, newest-deleted first (P8-S4). Restorable via
    ``POST {id}/untrash`` until the retention reaper purges them after 30 days (P8-S3)."""
    _require_household(principal)
    notes = await service.list_trashed(session)
    return [
        TrashedNote(id=n.id, title=n.title, deleted_at=d)
        for n in notes
        if (d := n.deleted_at) is not None
    ]


@notes_router.get("/{note_id}")
async def get_note(
    note_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> NoteResponse:
    _require_household(principal)
    note = await service.get_note(session, note_id=note_id)
    response.headers["ETag"] = f'"{note.version}"'
    return _response(note)


@notes_router.patch("/{note_id}", dependencies=[Depends(require_csrf)])
async def update_note(
    note_id: uuid.UUID,
    payload: NoteUpdate,
    request: Request,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> NoteResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    note = await service.update_note(
        session,
        household_id=household_id,
        author_id=principal.user_id,
        note_id=note_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{note.version}"'
    return _response(note)


@notes_router.get("/{note_id}/versions")
async def list_versions(
    note_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> list[NoteVersionResponse]:
    """The archived versions of a note (newest first; max 5, P7-S2)."""
    _require_household(principal)
    versions = await service.list_versions(session, note_id=note_id)
    return [
        NoteVersionResponse(
            version_no=v.version_no,
            title=v.title,
            body_md=v.body_md,
            edited_by=v.edited_by,
            created_at=v.created_at,
        )
        for v in versions
    ]


@notes_router.post("/{note_id}/restore", dependencies=[Depends(require_csrf)])
async def restore_version(
    note_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
    version_no: Annotated[int, Query(ge=1)],
) -> NoteResponse:
    """Restore a note's content from an archived version (P7-S2). The current content is archived
    first (undoable). 404 if the version is gone."""
    household_id = _require_household(principal)
    note = await service.restore_version(
        session,
        household_id=household_id,
        author_id=principal.user_id,
        note_id=note_id,
        version_no=version_no,
    )
    response.headers["ETag"] = f'"{note.version}"'
    return _response(note)


@notes_router.post("/{note_id}/untrash", dependencies=[Depends(require_csrf)])
async def untrash_note(
    note_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> NoteResponse:
    """Restore a soft-deleted note from the trash (P8-S4). 404 if it is not in the trash (already
    restored, never existed, or purged after the 30-day window)."""
    household_id = _require_household(principal)
    note = await service.untrash_note(session, household_id=household_id, note_id=note_id)
    response.headers["ETag"] = f'"{note.version}"'
    return _response(note)


@notes_router.post(
    "/{note_id}/to-task", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def convert_to_task(
    note_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> ToTaskResult:
    """Create a personal task from a note („Konvertieren-zu", P7-S3); the note stays."""
    household_id = _require_household(principal)
    task_id, title = await service.convert_to_task(
        session, household_id=household_id, note_id=note_id, author_id=principal.user_id
    )
    return ToTaskResult(task_id=task_id, title=title)


@notes_router.delete(
    "/{note_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_note(
    note_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_note(session, household_id=household_id, note_id=note_id)
