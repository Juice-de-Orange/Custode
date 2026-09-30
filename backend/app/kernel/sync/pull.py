"""Delta pull for the Sync-Batch (ARCHITECTURE §10). Keyset over ``(updated_at, id)`` across a
module's entities; tombstones (``deleted_at``) come back as ``op=delete``. No cursor = full sync.
A malformed or too-old cursor (past the 90-day tombstone window) → 410 ``resync_required``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.http.pagination import decode_cursor, encode_cursor
from app.kernel.http.problem import ProblemException
from app.kernel.sync.schemas import SyncChange, SyncPullResponse
from app.kernel.sync.spec import EntitySpec, ModuleSpec

TOMBSTONE_DAYS = 90


def _change(spec: EntitySpec, row: Any) -> SyncChange:
    deleted = row.deleted_at is not None
    return SyncChange(
        entity=spec.entity,
        id=row.id,
        op="delete" if deleted else "upsert",
        version=row.version,
        updated_at=row.updated_at,
        fields={} if deleted else {name: getattr(row, name) for name in spec.read_fields},
    )


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        u_str, id_str = decode_cursor(cursor)
        after = (datetime.fromisoformat(u_str), uuid.UUID(id_str))
    except (ValueError, KeyError) as exc:
        raise ProblemException(slug="resync_required", title="Cursor ungültig", status=410) from exc
    if after[0] < datetime.now(UTC) - timedelta(days=TOMBSTONE_DAYS):
        raise ProblemException(slug="resync_required", title="Cursor abgelaufen", status=410)
    return after


async def pull_changes(
    session: AsyncSession,
    spec: ModuleSpec,
    *,
    household_id: uuid.UUID,
    cursor: str | None,
    limit: int = 200,
) -> SyncPullResponse:
    """Return changes since *cursor* (or all if None), ordered by ``(updated_at, id)``; sets a
    ``next_cursor`` when more remain. Includes tombstones so deletes propagate."""
    after = _decode(cursor) if cursor else None

    rows: list[tuple[EntitySpec, Any]] = []
    for entity_spec in spec.entities.values():
        model: Any = entity_spec.model
        stmt = select(model).where(model.household_id == household_id)
        if after is not None:
            stmt = stmt.where(tuple_(model.updated_at, model.id) > after)
        stmt = stmt.order_by(model.updated_at, model.id).limit(limit)
        rows.extend((entity_spec, row) for row in (await session.execute(stmt)).scalars().all())

    rows.sort(key=lambda pair: (pair[1].updated_at, pair[1].id))
    page = rows[:limit]
    # Advance the high-water mark to the last returned row; echo the input cursor when the page is
    # empty (caught up). The client keeps pulling while it receives a full page (len == limit).
    next_cursor = encode_cursor(page[-1][1].updated_at, str(page[-1][1].id)) if page else cursor
    return SyncPullResponse(changes=[_change(es, row) for es, row in page], next_cursor=next_cursor)
