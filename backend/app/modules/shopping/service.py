"""shopping use-cases. The write path is the Sync-Batch — the service just binds the household's
field-group spec to the generic engine. Pull + reads land in S2."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.sync.apply import apply_batch
from app.kernel.sync.pull import pull_changes
from app.kernel.sync.schemas import SyncBatchResponse, SyncOp, SyncPullResponse
from app.modules.shopping.models import ShoppingList
from app.modules.shopping.spec import SHOPPING_SPEC

# Namespace for deterministic op ids derived from a household (ensure_default_list idempotency).
_LIST_NS = uuid.uuid5(uuid.NAMESPACE_URL, "custode:shopping:default-list")
# Technical default-list name (NOT the marketing brand — generic noun, CLAUDE.md BRAND_NAME rule).
_DEFAULT_LIST_NAME = "Einkauf"


async def apply_shopping_batch(
    session: AsyncSession, *, household_id: uuid.UUID, user_id: uuid.UUID, ops: list[SyncOp]
) -> SyncBatchResponse:
    """Apply a batch of offline shopping ops (LWW per field group, idempotent). Emits
    ``shopping.changed`` for SSE live-sync; returns the authoritative server state."""
    return await apply_batch(
        session, SHOPPING_SPEC, household_id=household_id, user_id=user_id, ops=ops
    )


async def pull_shopping(
    session: AsyncSession, *, household_id: uuid.UUID, cursor: str | None, limit: int = 200
) -> SyncPullResponse:
    """Delta pull of shopping changes since *cursor* (or full sync if None)."""
    return await pull_changes(
        session, SHOPPING_SPEC, household_id=household_id, cursor=cursor, limit=limit
    )


async def ensure_default_list(
    session: AsyncSession, *, household_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID:
    """Return a target list id for a server-originated item (e.g. a Zuruf, ADR-0038): the
    household's most-recently-updated list, or a freshly created default one. The list is created
    **through the same Sync-Batch path** (no second write path, ADR-0032) with a deterministic
    ``client_op_id`` so repeated calls never create duplicates. The client picks it up on the next
    delta pull."""
    existing = await session.scalar(
        select(ShoppingList.id)
        .where(ShoppingList.deleted_at.is_(None))
        .order_by(ShoppingList.updated_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    new_id = uuid.uuid5(_LIST_NS, f"list:{household_id}")
    await apply_shopping_batch(
        session,
        household_id=household_id,
        user_id=user_id,
        ops=[
            SyncOp(
                client_op_id=uuid.uuid5(_LIST_NS, f"op:{household_id}"),
                entity="shopping_list",
                id=new_id,
                op="upsert",
                fields={"name": _DEFAULT_LIST_NAME},
            )
        ],
    )
    return new_id
