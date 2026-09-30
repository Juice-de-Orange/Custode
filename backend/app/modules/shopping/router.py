"""HTTP layer for ``shopping`` — the Sync-Batch push (ARCHITECTURE §10). Pull (GET) lands in S2."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.kernel.auth.context import Principal
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.sync.schemas import SyncBatchRequest, SyncBatchResponse, SyncPullResponse
from app.modules.shopping import service

shopping_router = APIRouter(prefix="/v1/sync/shopping", tags=["shopping"])


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


@shopping_router.post("/batch", dependencies=[Depends(require_csrf)])
async def sync_batch(
    payload: SyncBatchRequest, principal: CurrentPrincipal, session: ScopedSession
) -> SyncBatchResponse:
    """Push offline ops; returns the authoritative server state of every touched entity."""
    household_id = _require_household(principal)
    return await service.apply_shopping_batch(
        session, household_id=household_id, user_id=principal.user_id, ops=payload.ops
    )


@shopping_router.get("")
async def sync_pull(
    principal: CurrentPrincipal,
    session: ScopedSession,
    cursor: str | None = None,
    limit: int = 200,
) -> SyncPullResponse:
    """Delta pull of shopping changes since ``cursor`` (full sync if omitted). 410 → resync."""
    household_id = _require_household(principal)
    return await service.pull_shopping(
        session, household_id=household_id, cursor=cursor, limit=min(max(limit, 1), 500)
    )
