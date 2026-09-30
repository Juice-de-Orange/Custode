"""guides use-cases (KONZEPT §5, Phase 7). Runs on the request's RLS-scoped session. Online-first:
PATCH + If-Match (``version`` is the ETag). List supports an optional category filter and a German
full-text search (``q``) over the generated ``search_tsv`` column, ranked by relevance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.storage import get_storage
from app.modules.guides.models import Guide, GuideAttachment
from app.modules.guides.schemas import GuideCreate, GuideUpdate

# The German FTS column is generated in the DB (migration 0047); reference it by name.
_TSV: ColumnElement[object] = literal_column("search_tsv")


async def create_guide(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, data: GuideCreate
) -> Guide:
    """Create a guide; emits ``guide.created``."""
    guide = Guide(
        household_id=household_id,
        author_id=author_id,
        title=data.title,
        body_md=data.body_md,
        category=data.category,
        tags=list(data.tags),
        contact_id=data.contact_id,
    )
    session.add(guide)
    await emit(session, type="guide.created", household_id=household_id, payload={})
    await session.flush()
    return guide


async def list_guides(
    session: AsyncSession, *, q: str | None = None, category: str | None = None
) -> list[Guide]:
    """The household's guides (RLS-scoped). ``category`` filters exactly; ``q`` runs a German FTS
    (``plainto_tsquery('german', q)``) ranked by relevance. Without ``q``: newest update first."""
    stmt = select(Guide).where(Guide.deleted_at.is_(None))
    if category:
        stmt = stmt.where(Guide.category == category)
    if q and q.strip():
        tsquery = func.plainto_tsquery("german", q)
        stmt = stmt.where(_TSV.op("@@")(tsquery)).order_by(
            func.ts_rank(_TSV, tsquery).desc(), Guide.updated_at.desc()
        )
    else:
        stmt = stmt.order_by(Guide.updated_at.desc())
    return list(await session.scalars(stmt))


async def get_guide(session: AsyncSession, *, guide_id: uuid.UUID) -> Guide:
    """One guide of the active household (RLS hides other households -> 404)."""
    guide = await session.get(Guide, guide_id)
    if guide is None or guide.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Anleitung nicht gefunden", status=404)
    return guide


async def update_guide(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    guide_id: uuid.UUID,
    expected_version: int,
    data: GuideUpdate,
) -> Guide:
    """Patch a guide under optimistic concurrency (``expected_version`` = If-Match). 412 if stale.
    Emits ``guide.updated``."""
    guide = await get_guide(session, guide_id=guide_id)
    if guide.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Anleitung zwischenzeitlich geändert", status=412
        )
    if data.title is not None:
        guide.title = data.title
    if data.body_md is not None:
        guide.body_md = data.body_md
    if data.category is not None:
        guide.category = data.category
    if data.tags is not None:
        guide.tags = list(data.tags)
    # ``contact_id`` is nullable, so "absent" (leave as is) and "null" (clear) must be told apart
    # via the set of explicitly provided fields rather than a None check.
    if "contact_id" in data.model_fields_set:
        guide.contact_id = data.contact_id
    await emit(
        session,
        type="guide.updated",
        household_id=household_id,
        payload={"guide_id": str(guide_id)},
    )
    await session.flush()
    await session.refresh(guide, attribute_names=["version", "updated_at"])
    return guide


async def delete_guide(
    session: AsyncSession, *, household_id: uuid.UUID, guide_id: uuid.UUID
) -> None:
    """Soft-delete a guide and **cascade** to its attachments (blob + row). Emits ``guide.deleted``.
    404 if already gone."""
    guide = await get_guide(session, guide_id=guide_id)
    for attachment in await list_attachments(session, guide_id=guide_id):
        _remove_blob(attachment.storage_key)
        attachment.deleted_at = datetime.now(UTC)
    guide.deleted_at = datetime.now(UTC)
    await emit(
        session,
        type="guide.deleted",
        household_id=household_id,
        payload={"guide_id": str(guide_id)},
    )
    await session.flush()


# --- Attachments (KONZEPT §5, P7-S22; bytes in blob storage, only metadata in the DB — ADR-0033) --


# Storage keys are server-generated + flat (the filesystem backend keeps only the last path
# segment); the attachment id (a uuid) makes them unique without leaking the household/guide layout.
def _attachment_key(attachment_id: uuid.UUID) -> str:
    return f"guide-attachment-{attachment_id}"


def _remove_blob(storage_key: str) -> None:
    """Best-effort blob removal — never fails the request if the backend is a Null/absent store."""
    storage = get_storage()
    if storage.enabled:
        storage.delete(storage_key)


async def add_attachment(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    guide_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
) -> GuideAttachment:
    """Store an uploaded file for a guide: the bytes go to blob storage, only metadata to the DB.
    404 if the guide is gone. Emits ``guide.updated`` (the list is part of the guide detail)."""
    await get_guide(session, guide_id=guide_id)  # 404s if the guide is gone / other household
    attachment_id = uuid.uuid4()
    key = _attachment_key(attachment_id)
    get_storage().put(key, data)
    attachment = GuideAttachment(
        id=attachment_id,
        household_id=household_id,
        guide_id=guide_id,
        filename=filename,
        content_type=content_type,
        byte_size=len(data),
        storage_key=key,
        uploaded_by=uploaded_by,
    )
    session.add(attachment)
    await emit(
        session,
        type="guide.updated",
        household_id=household_id,
        payload={"guide_id": str(guide_id)},
    )
    await session.flush()
    return attachment


async def list_attachments(session: AsyncSession, *, guide_id: uuid.UUID) -> list[GuideAttachment]:
    """A guide's attachments (RLS-scoped), oldest first."""
    rows = await session.scalars(
        select(GuideAttachment)
        .where(GuideAttachment.guide_id == guide_id, GuideAttachment.deleted_at.is_(None))
        .order_by(GuideAttachment.created_at.asc())
    )
    return list(rows)


async def get_attachment(session: AsyncSession, *, attachment_id: uuid.UUID) -> GuideAttachment:
    """One attachment of the active household (RLS hides other households -> 404)."""
    attachment = await session.get(GuideAttachment, attachment_id)
    if attachment is None or attachment.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Anhang nicht gefunden", status=404)
    return attachment


def read_attachment_bytes(attachment: GuideAttachment) -> bytes | None:
    """Read the stored bytes for an already-loaded (RLS-scoped) attachment."""
    return get_storage().get(attachment.storage_key)


async def delete_attachment(
    session: AsyncSession, *, household_id: uuid.UUID, attachment_id: uuid.UUID
) -> None:
    """Remove an attachment's blob and soft-delete its row. Emits ``guide.updated``. 404 if gone."""
    attachment = await get_attachment(session, attachment_id=attachment_id)
    _remove_blob(attachment.storage_key)
    attachment.deleted_at = datetime.now(UTC)
    await emit(
        session,
        type="guide.updated",
        household_id=household_id,
        payload={"guide_id": str(attachment.guide_id)},
    )
    await session.flush()
