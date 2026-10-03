"""vault use-cases (KONZEPT §5, ADR-0067). Runs on the request's RLS-scoped session. Everything the
server touches here is **opaque ciphertext** — it never decrypts and never logs ``wrapped_key`` /
``ciphertext`` / ``*_meta``. Online-first (PATCH + If-Match for items); soft-delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.vault.models import VaultItem, VaultKeyEnvelope
from app.modules.vault.schemas import EnvelopeUpsert, VaultItemCreate, VaultItemUpdate

# --- Key envelopes ---------------------------------------------------------------------------


async def upsert_envelope(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID, data: EnvelopeUpsert
) -> VaultKeyEnvelope:
    """Store a wrapped household-key envelope. A ``passphrase`` envelope binds to the requesting
    member and may be replaced (passphrase change; idempotent per member/key_version). A
    ``recovery`` envelope is household-wide (``member_id`` NULL) and **write-once**: it is the one
    copy of the household key every member can fall back on, so a second "setup" must never
    replace it (409 ``vault_already_set_up``). Emits ``vault.key_changed``."""
    if data.kind == "recovery":
        return await _create_recovery_envelope(session, household_id=household_id, data=data)
    existing = await session.scalar(
        select(VaultKeyEnvelope).where(
            VaultKeyEnvelope.kind == "passphrase",
            VaultKeyEnvelope.key_version == data.key_version,
            VaultKeyEnvelope.member_id == member_id,
            VaultKeyEnvelope.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.wrapped_key = data.wrapped_key
        existing.wrap_meta = data.wrap_meta
        envelope = existing
    else:
        envelope = VaultKeyEnvelope(
            household_id=household_id,
            member_id=member_id,
            kind="passphrase",
            key_version=data.key_version,
            wrapped_key=data.wrapped_key,
            wrap_meta=data.wrap_meta,
        )
        session.add(envelope)
    await emit(session, type="vault.key_changed", household_id=household_id, payload={})
    await session.flush()
    return envelope


def _already_set_up() -> ProblemException:
    return ProblemException(
        slug="vault_already_set_up", title="Der Tresor ist bereits eingerichtet", status=409
    )


async def _create_recovery_envelope(
    session: AsyncSession, *, household_id: uuid.UUID, data: EnvelopeUpsert
) -> VaultKeyEnvelope:
    """Create the household's recovery envelope — once. The server cannot tell whether a second
    envelope wraps the same household key (it is opaque by design), so it cannot allow a
    replacement at all: a client that "sets up" an existing vault would swap the key under every
    other member, whose entries and recovery code are then lost for good. **Any** live recovery
    envelope blocks, not only one with the same ``key_version`` — a higher version would shadow
    the real one just as well. (Key rotation is not built; it gets its own path and ADR.)

    A byte-identical replay returns the stored envelope, so a retried setup request stays
    idempotent."""
    existing = await session.scalar(
        select(VaultKeyEnvelope)
        .where(VaultKeyEnvelope.kind == "recovery", VaultKeyEnvelope.deleted_at.is_(None))
        .order_by(VaultKeyEnvelope.key_version.desc())
        .limit(1)
    )
    if existing is not None:
        if (
            existing.key_version == data.key_version
            and existing.wrapped_key == data.wrapped_key
            and existing.wrap_meta == data.wrap_meta
        ):
            return existing
        raise _already_set_up()
    envelope = VaultKeyEnvelope(
        household_id=household_id,
        member_id=None,
        kind="recovery",
        key_version=data.key_version,
        wrapped_key=data.wrapped_key,
        wrap_meta=data.wrap_meta,
    )
    session.add(envelope)
    await emit(session, type="vault.key_changed", household_id=household_id, payload={})
    try:
        await session.flush()
    except IntegrityError as exc:
        # Two members racing through setup: the partial unique index (one recovery envelope per
        # household and key_version) decides, and the loser gets the same answer as a latecomer.
        raise _already_set_up() from exc
    return envelope


async def list_my_envelopes(
    session: AsyncSession, *, member_id: uuid.UUID
) -> list[VaultKeyEnvelope]:
    """The envelopes the requesting member can unlock with: their own passphrase envelope(s) plus
    the household's recovery envelope(s). RLS scopes to the household."""
    rows = await session.scalars(
        select(VaultKeyEnvelope)
        .where(
            or_(
                VaultKeyEnvelope.member_id == member_id,
                VaultKeyEnvelope.kind == "recovery",
            ),
            VaultKeyEnvelope.deleted_at.is_(None),
        )
        .order_by(VaultKeyEnvelope.key_version.desc())
    )
    return list(rows)


# --- Items -----------------------------------------------------------------------------------


async def create_item(
    session: AsyncSession, *, household_id: uuid.UUID, author_id: uuid.UUID, data: VaultItemCreate
) -> VaultItem:
    """Store an encrypted secret; emits ``vault.item_changed``."""
    item = VaultItem(
        household_id=household_id,
        author_id=author_id,
        key_version=data.key_version,
        ciphertext=data.ciphertext,
        item_meta=data.item_meta,
    )
    session.add(item)
    await emit(session, type="vault.item_changed", household_id=household_id, payload={})
    await session.flush()
    return item


async def list_items(session: AsyncSession) -> list[VaultItem]:
    """The household's vault items (RLS-scoped), newest first."""
    rows = await session.scalars(
        select(VaultItem)
        .where(VaultItem.deleted_at.is_(None))
        .order_by(VaultItem.created_at.desc())
    )
    return list(rows)


async def get_item(session: AsyncSession, *, item_id: uuid.UUID) -> VaultItem:
    """One vault item of the active household (RLS hides other households -> 404)."""
    item = await session.get(VaultItem, item_id)
    if item is None or item.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Vault-Eintrag nicht gefunden", status=404)
    return item


async def update_item(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    item_id: uuid.UUID,
    expected_version: int,
    data: VaultItemUpdate,
) -> VaultItem:
    """Patch an encrypted secret under optimistic concurrency (``expected_version`` = If-Match). 412
    if stale. Emits ``vault.item_changed``."""
    item = await get_item(session, item_id=item_id)
    if item.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Vault-Eintrag zwischenzeitlich geändert", status=412
        )
    if data.ciphertext is not None:
        item.ciphertext = data.ciphertext
    if data.item_meta is not None:
        item.item_meta = data.item_meta
    if data.key_version is not None:
        item.key_version = data.key_version
    await emit(session, type="vault.item_changed", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(item, attribute_names=["version", "updated_at"])
    return item


async def delete_item(
    session: AsyncSession, *, household_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    """Soft-delete a vault item. Emits ``vault.item_changed``. 404 if already gone."""
    item = await get_item(session, item_id=item_id)
    item.deleted_at = datetime.now(UTC)
    await emit(session, type="vault.item_changed", household_id=household_id, payload={})
    await session.flush()
