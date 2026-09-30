"""notes use-cases. Run on the request's RLS-scoped session (``household_id = app.household_id``);
the dependency commits the unit of work. Online-first: PATCH + If-Match (``version`` is the ETag,
bumped by the shared trigger). Pinned notes sort first, then most-recently-updated."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.notes.models import Note, NoteVersion
from app.modules.notes.schemas import NoteCreate, NoteUpdate
from app.modules.tasks import api as tasks_api

# How many previous versions to keep per note (KONZEPT §5: „5 Versionen").
_KEEP_VERSIONS = 5


async def _snapshot_and_prune(session: AsyncSession, *, note: Note, edited_by: uuid.UUID) -> None:
    """Archive the note's **current** content (``version_no`` = its current ``version``), then prune
    to the most recent ``_KEEP_VERSIONS``. Call BEFORE mutating the note's fields."""
    session.add(
        NoteVersion(
            household_id=note.household_id,
            note_id=note.id,
            version_no=note.version,
            title=note.title,
            body_md=note.body_md,
            edited_by=edited_by,
        )
    )
    await session.flush()
    keep = (
        select(NoteVersion.version_no)
        .where(NoteVersion.note_id == note.id)
        .order_by(NoteVersion.version_no.desc())
        .limit(_KEEP_VERSIONS)
    )
    await session.execute(
        delete(NoteVersion).where(
            NoteVersion.note_id == note.id, NoteVersion.version_no.not_in(keep)
        )
    )


async def create_note(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, data: NoteCreate
) -> Note:
    """Create a note; emits ``note.created``."""
    note = Note(
        household_id=household_id,
        author_id=author_id,
        title=data.title,
        body_md=data.body_md,
        pinned=data.pinned,
    )
    session.add(note)
    await emit(session, type="note.created", household_id=household_id, payload={})
    await session.flush()
    return note


async def list_notes(session: AsyncSession, *, pinned_only: bool = False) -> list[Note]:
    """The active household's notes (RLS-scoped). Pinned first, then newest update."""
    stmt = select(Note).where(Note.deleted_at.is_(None))
    if pinned_only:
        stmt = stmt.where(Note.pinned.is_(True))
    stmt = stmt.order_by(Note.pinned.desc(), Note.updated_at.desc())
    return list(await session.scalars(stmt))


async def get_note(session: AsyncSession, *, note_id: uuid.UUID) -> Note:
    """One *active* note of the active household (RLS hides other households -> 404)."""
    note = await session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Notiz nicht gefunden", status=404)
    return note


async def list_trashed(session: AsyncSession) -> list[Note]:
    """Soft-deleted notes of the active household, most-recently-deleted first (P8-S4). They stay
    here — and are restorable — until the retention reaper purges them after the 30-day window."""
    stmt = select(Note).where(Note.deleted_at.is_not(None)).order_by(Note.deleted_at.desc())
    return list(await session.scalars(stmt))


async def update_note(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    author_id: uuid.UUID,
    note_id: uuid.UUID,
    expected_version: int,
    data: NoteUpdate,
) -> Note:
    """Patch a note under optimistic concurrency (``expected_version`` = If-Match). 412 if stale. A
    content change (title/body) first archives the previous version (P7-S2). Emits ``note.updated``.
    """
    note = await get_note(session, note_id=note_id)
    if note.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Notiz zwischenzeitlich geändert", status=412
        )
    # Archive the pre-edit content (only when title/body actually change — a pure pin toggle is not
    # a content edit and should not consume a version slot).
    if (data.title is not None and data.title != note.title) or (
        data.body_md is not None and data.body_md != note.body_md
    ):
        await _snapshot_and_prune(session, note=note, edited_by=author_id)
    if data.title is not None:
        note.title = data.title
    if data.body_md is not None:
        note.body_md = data.body_md
    if data.pinned is not None:
        note.pinned = data.pinned
    await emit(
        session, type="note.updated", household_id=household_id, payload={"note_id": str(note_id)}
    )
    await session.flush()
    await session.refresh(note, attribute_names=["version", "updated_at"])
    return note


async def list_versions(session: AsyncSession, *, note_id: uuid.UUID) -> list[NoteVersion]:
    """The archived versions of a note (newest first; max ``_KEEP_VERSIONS``). 404 if the note is
    gone. RLS-scoped."""
    await get_note(session, note_id=note_id)
    rows = await session.scalars(
        select(NoteVersion)
        .where(NoteVersion.note_id == note_id)
        .order_by(NoteVersion.version_no.desc())
    )
    return list(rows)


async def restore_version(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    note_id: uuid.UUID,
    version_no: int,
    author_id: uuid.UUID,
) -> Note:
    """Restore a note's title/body from an archived version (P7-S2). This is itself an edit: the
    current content is first archived (so a restore is undoable), then the old content is applied.
    404 if the note or the version is gone. Emits ``note.updated``."""
    note = await get_note(session, note_id=note_id)
    version = await session.scalar(
        select(NoteVersion).where(
            NoteVersion.note_id == note_id, NoteVersion.version_no == version_no
        )
    )
    if version is None:
        raise ProblemException(slug="not_found", title="Version nicht gefunden", status=404)
    await _snapshot_and_prune(session, note=note, edited_by=author_id)
    note.title = version.title
    note.body_md = version.body_md
    await emit(
        session, type="note.updated", household_id=household_id, payload={"note_id": str(note_id)}
    )
    await session.flush()
    await session.refresh(note, attribute_names=["version", "updated_at"])
    return note


async def convert_to_task(
    session: AsyncSession, *, household_id: uuid.UUID, note_id: uuid.UUID, author_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    """„Konvertieren-zu Aufgabe" (P7-S3, ADR-0061): create a personal task from a note, assigned to
    the caller, via ``tasks.api.create_personal_task`` (points 0, one-way). The note's title becomes
    the task title; the note itself stays (non-destructive). Returns ``(task_id, title)``; 404 if
    the note is gone."""
    note = await get_note(session, note_id=note_id)
    task = await tasks_api.create_personal_task(
        session, household_id=household_id, title=note.title, assigned_to=author_id
    )
    return task.id, note.title


async def delete_note(
    session: AsyncSession, *, household_id: uuid.UUID, note_id: uuid.UUID
) -> None:
    """Soft-delete a note (history kept). Emits ``note.deleted``. Idempotent-ish (404 if gone)."""
    note = await get_note(session, note_id=note_id)
    note.deleted_at = datetime.now(UTC)
    await emit(
        session, type="note.deleted", household_id=household_id, payload={"note_id": str(note_id)}
    )
    await session.flush()


async def untrash_note(
    session: AsyncSession, *, household_id: uuid.UUID, note_id: uuid.UUID
) -> Note:
    """Restore a soft-deleted note from the trash (P8-S4): clear ``deleted_at``. 404 if the note is
    gone (purged or never existed) or is not actually trashed. Emits ``note.updated`` so the live
    notes list refreshes. RLS keeps this scoped to the active household."""
    note = await session.get(Note, note_id)
    if note is None or note.deleted_at is None:
        raise ProblemException(slug="not_found", title="Notiz nicht im Papierkorb", status=404)
    note.deleted_at = None
    await emit(
        session, type="note.updated", household_id=household_id, payload={"note_id": str(note_id)}
    )
    await session.flush()
    return note
