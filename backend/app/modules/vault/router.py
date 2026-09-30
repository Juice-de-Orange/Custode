"""HTTP layer for ``vault`` (KONZEPT §5, ADR-0067). End-to-end encrypted secrets — the server stores
and returns only opaque ciphertext, never decrypting. Household-scoped (RLS), online-first (items
use PATCH + If-Match). **Children and guests are excluded** (Root-CLAUDE.md): member/admin only."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import ScopedSession, require_role
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.vault import service
from app.modules.vault.models import VaultItem, VaultKeyEnvelope
from app.modules.vault.schemas import (
    EnvelopeResponse,
    EnvelopeUpsert,
    VaultItemCreate,
    VaultItemResponse,
    VaultItemSummary,
    VaultItemUpdate,
)

vault_router = APIRouter(prefix="/v1/vault", tags=["vault"])

# Vault is for adults: children + guests are excluded (Root-CLAUDE.md, like marketplace/capture).
VaultPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _envelope(envelope: VaultKeyEnvelope) -> EnvelopeResponse:
    return EnvelopeResponse(
        id=envelope.id,
        member_id=envelope.member_id,
        kind=envelope.kind,
        key_version=envelope.key_version,
        wrapped_key=envelope.wrapped_key,
        wrap_meta=envelope.wrap_meta,
        created_at=envelope.created_at,
    )


def _item(item: VaultItem) -> VaultItemResponse:
    return VaultItemResponse(
        id=item.id,
        author_id=item.author_id,
        key_version=item.key_version,
        ciphertext=item.ciphertext,
        item_meta=item.item_meta,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# --- Key envelopes ---------------------------------------------------------------------------


@vault_router.get("/keys")
async def list_keys(principal: VaultPrincipal, session: ScopedSession) -> list[EnvelopeResponse]:
    """The wrapped household-key envelopes the caller can unlock with (passphrase + recovery)."""
    _require_household(principal)
    envelopes = await service.list_my_envelopes(session, member_id=principal.user_id)
    return [_envelope(e) for e in envelopes]


@vault_router.put("/keys", dependencies=[Depends(require_csrf)])
async def put_key(
    payload: EnvelopeUpsert, principal: VaultPrincipal, session: ScopedSession
) -> EnvelopeResponse:
    """Store/replace a wrapped household-key envelope (idempotent per member/kind/version)."""
    household_id = _require_household(principal)
    envelope = await service.upsert_envelope(
        session, household_id=household_id, member_id=principal.user_id, data=payload
    )
    return _envelope(envelope)


# --- Items -----------------------------------------------------------------------------------


@vault_router.get("/items")
async def list_items(principal: VaultPrincipal, session: ScopedSession) -> list[VaultItemSummary]:
    """The household's vault items — **without** the secret ciphertext (fetch one to decrypt it)."""
    _require_household(principal)
    items = await service.list_items(session)
    return [
        VaultItemSummary(
            id=item.id,
            key_version=item.key_version,
            item_meta=item.item_meta,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@vault_router.post(
    "/items", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_item(
    payload: VaultItemCreate,
    principal: VaultPrincipal,
    session: ScopedSession,
    response: Response,
) -> VaultItemResponse:
    household_id = _require_household(principal)
    item = await service.create_item(
        session, household_id=household_id, author_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{item.version}"'
    return _item(item)


@vault_router.get("/items/{item_id}")
async def get_item(
    item_id: uuid.UUID,
    principal: VaultPrincipal,
    session: ScopedSession,
    response: Response,
) -> VaultItemResponse:
    _require_household(principal)
    item = await service.get_item(session, item_id=item_id)
    response.headers["ETag"] = f'"{item.version}"'
    return _item(item)


@vault_router.patch("/items/{item_id}", dependencies=[Depends(require_csrf)])
async def update_item(
    item_id: uuid.UUID,
    payload: VaultItemUpdate,
    request: Request,
    principal: VaultPrincipal,
    session: ScopedSession,
    response: Response,
) -> VaultItemResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    item = await service.update_item(
        session,
        household_id=household_id,
        item_id=item_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{item.version}"'
    return _item(item)


@vault_router.delete(
    "/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_item(
    item_id: uuid.UUID, principal: VaultPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_item(session, household_id=household_id, item_id=item_id)
