"""links use-cases (KONZEPT §5.12 / Phase 7). Runs on the request's RLS-scoped session. Links are
generic: each endpoint is a ``(type, id)`` pair referencing any object without a cross-module FK.
Endpoints are canonicalised (smaller ``(type, id)`` first) so a link is direction-independent and
idempotent. Online-first; soft-delete. ACL / attachments / pickers are later slices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.links.models import ObjectLink
from app.modules.links.schemas import LinkCreate

# A canonical, direction-independent ordering for the two endpoints. Comparing on
# ``(type, str(id))`` keeps the smaller endpoint in ``src`` so ``(a, b)`` and ``(b, a)`` collapse
# to one row (the unique index then rejects symmetric duplicates).
_Endpoint = tuple[str, uuid.UUID]


def _canonical(a: _Endpoint, b: _Endpoint) -> tuple[_Endpoint, _Endpoint]:
    return (a, b) if (a[0], str(a[1])) <= (b[0], str(b[1])) else (b, a)


async def create_link(
    session: AsyncSession, *, household_id: uuid.UUID, created_by: uuid.UUID, data: LinkCreate
) -> ObjectLink:
    """Link two objects (idempotent). Self-links are rejected (422). Re-linking the same pair with
    the same relation returns the existing link. Emits ``link.created`` for a new link."""
    a: _Endpoint = (data.a_type, data.a_id)
    b: _Endpoint = (data.b_type, data.b_id)
    if a == b:
        raise ProblemException(
            slug="invalid", title="Objekt nicht mit sich selbst verknüpfbar", status=422
        )
    (src_type, src_id), (dst_type, dst_id) = _canonical(a, b)

    existing = await session.scalar(
        select(ObjectLink).where(
            ObjectLink.src_type == src_type,
            ObjectLink.src_id == src_id,
            ObjectLink.dst_type == dst_type,
            ObjectLink.dst_id == dst_id,
            ObjectLink.relation == data.relation,
            ObjectLink.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing

    link = ObjectLink(
        household_id=household_id,
        src_type=src_type,
        src_id=src_id,
        dst_type=dst_type,
        dst_id=dst_id,
        relation=data.relation,
        created_by=created_by,
    )
    session.add(link)
    await emit(session, type="link.created", household_id=household_id, payload={})
    await session.flush()
    return link


async def list_links(
    session: AsyncSession, *, object_type: str, object_id: uuid.UUID
) -> list[ObjectLink]:
    """Every link touching one object (it may sit on either endpoint), RLS-scoped, oldest first."""
    rows = await session.scalars(
        select(ObjectLink)
        .where(
            or_(
                (ObjectLink.src_type == object_type) & (ObjectLink.src_id == object_id),
                (ObjectLink.dst_type == object_type) & (ObjectLink.dst_id == object_id),
            ),
            ObjectLink.deleted_at.is_(None),
        )
        .order_by(ObjectLink.created_at.asc())
    )
    return list(rows)


async def delete_link(
    session: AsyncSession, *, household_id: uuid.UUID, link_id: uuid.UUID
) -> None:
    """Soft-delete a link (any household member may unlink — links are shared metadata, not authored
    content). 404 if gone. RLS scopes to the household. Emits ``link.deleted``."""
    link = await session.get(ObjectLink, link_id)
    if link is None or link.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Verknüpfung nicht gefunden", status=404)
    link.deleted_at = datetime.now(UTC)
    await emit(session, type="link.deleted", household_id=household_id, payload={})
    await session.flush()


async def purge_for_object(
    session: AsyncSession, *, household_id: uuid.UUID, object_type: str, object_id: uuid.UUID
) -> int:
    """Soft-delete every (still-live) link touching one object on **either** endpoint — used by the
    reaper when a linked object is deleted (P7-S20). Keyed only on ``(type, id)``; ``links`` never
    reads the foreign module. Idempotent: a re-run matches no live rows. Emits ``link.deleted`` once
    when it removed anything. Returns the number of links removed."""
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(ObjectLink)
            .where(
                or_(
                    (ObjectLink.src_type == object_type) & (ObjectLink.src_id == object_id),
                    (ObjectLink.dst_type == object_type) & (ObjectLink.dst_id == object_id),
                ),
                ObjectLink.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        ),
    )
    removed = result.rowcount or 0
    if removed:
        await emit(session, type="link.deleted", household_id=household_id, payload={})
        await session.flush()
    return removed
