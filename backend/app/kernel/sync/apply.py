"""Apply a Sync-Batch (ARCHITECTURE §10, ADR-0032). Runs on the request's RLS-scoped session in one
transaction: the idempotency marker + the entity writes commit together, so a half-applied batch is
impossible.

LWW per field group is delivered by *merging only the fields present in an op*: a "check" op carries
only ``checked``, a "rename" op only label/qty/unit/category — they never overwrite one another, and
the later-received op wins per field. ``version`` is bumped by the shared DB trigger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.sync.models import SyncClientOp
from app.kernel.sync.schemas import ServerEntityState, SyncBatchResponse, SyncOp
from app.kernel.sync.spec import EntitySpec, ModuleSpec


def _coerce(spec: EntitySpec, fields: dict[str, Any]) -> dict[str, Any]:
    out = dict(fields)
    for name in spec.uuid_fields:
        if isinstance(out.get(name), str):
            try:
                out[name] = uuid.UUID(out[name])
            except ValueError as exc:
                raise ProblemException(
                    slug="sync_invalid_field", title=f"Ungültiges UUID-Feld: {name}", status=422
                ) from exc
    return out


def _resolve_writes(spec: EntitySpec, fields: dict[str, Any], user_id: uuid.UUID) -> dict[str, Any]:
    """Map an op's fields to column writes. Real fields pass through; a server-owner trigger
    (e.g. ``checked``/``reserve``) sets its owner column to the acting user (NULL when falsy). The
    owner column is never client-writable, so a client cannot spoof who reserved/checked."""
    writes: dict[str, Any] = {}
    for name, value in fields.items():
        if name in spec.fields:
            writes[name] = value
        owner_col = spec.server_owner_fields.get(name)
        if owner_col is not None:
            writes[owner_col] = user_id if value else None
    return writes


def _transitions(
    spec: EntitySpec,
    fields: dict[str, Any],
    *,
    olds: dict[str, Any],
    row_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[tuple[str, dict[str, Any]]]:
    """Collect domain events for fields that transitioned falsy -> truthy on this op (``olds`` empty
    for a create). Payload carries the row id + acting user so a subscriber can react (e.g. capture
    arming a task on ``shopping.item.checked``)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for fld, event_type in spec.transition_events.items():
        if fld in fields and fields.get(fld) and not olds.get(fld):
            out.append((event_type, {"id": str(row_id), "user_id": str(user_id)}))
    return out


def _server_state(spec: EntitySpec, row: Any) -> ServerEntityState:
    return ServerEntityState(
        entity=spec.entity,
        id=row.id,
        version=row.version,
        deleted=row.deleted_at is not None,
        fields={name: getattr(row, name) for name in spec.read_fields},
    )


async def _claim_op(
    session: AsyncSession, household_id: uuid.UUID, client_op_id: uuid.UUID
) -> bool:
    """Insert the idempotency marker. Returns True if we claimed it (first time → apply), False on
    conflict (already applied → skip apply, just return current state)."""
    stmt = (
        pg_insert(SyncClientOp)
        .values(household_id=household_id, client_op_id=client_op_id)
        .on_conflict_do_nothing(constraint="uq_sync_client_ops")
        .returning(SyncClientOp.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def apply_batch(
    session: AsyncSession,
    spec: ModuleSpec,
    *,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    ops: list[SyncOp],
) -> SyncBatchResponse:
    """Apply each op (idempotent, LWW field-merge); return the authoritative server state of every
    touched entity. Raises 422 on an unknown entity / disallowed field / missing create field."""
    applied: list[ServerEntityState] = []
    changed = False
    transitions: list[
        tuple[str, dict[str, Any]]
    ] = []  # (event_type, payload), emitted after writes
    for op in ops:
        entity_spec = spec.entities.get(op.entity)
        if entity_spec is None:
            raise ProblemException(
                slug="sync_unknown_entity", title=f"Unbekannte Entität: {op.entity}", status=422
            )
        unknown = set(op.fields) - entity_spec.fields - set(entity_spec.server_owner_fields)
        if unknown:
            raise ProblemException(
                slug="sync_unknown_field", title=f"Unerlaubte Felder: {sorted(unknown)}", status=422
            )

        claimed = await _claim_op(session, household_id, op.client_op_id)
        row: Any = await session.get(entity_spec.model, op.id)

        if claimed:
            fields = _coerce(entity_spec, op.fields)
            if op.op == "delete":
                if row is not None and row.deleted_at is None:
                    row.deleted_at = datetime.now(UTC)
                    changed = True
            elif row is None:
                missing = entity_spec.required_on_create - set(fields)
                if missing:
                    raise ProblemException(
                        slug="sync_missing_fields",
                        title=f"Fehlende Pflichtfelder: {sorted(missing)}",
                        status=422,
                    )
                writes = _resolve_writes(entity_spec, fields, user_id)
                kwargs: dict[str, Any] = {"id": op.id, "household_id": household_id, **writes}
                if entity_spec.owner_field is not None:
                    kwargs[entity_spec.owner_field] = user_id
                row = entity_spec.model(**kwargs)
                session.add(row)
                changed = True
                transitions.extend(
                    _transitions(entity_spec, fields, olds={}, row_id=op.id, user_id=user_id)
                )
            else:
                olds = {fld: getattr(row, fld, None) for fld in entity_spec.transition_events}
                for name, value in _resolve_writes(entity_spec, fields, user_id).items():
                    setattr(row, name, value)
                changed = True
                transitions.extend(
                    _transitions(entity_spec, fields, olds=olds, row_id=row.id, user_id=user_id)
                )
            await session.flush()

        if row is not None:
            await session.refresh(row)
            applied.append(_server_state(entity_spec, row))

    if changed:
        await emit(session, type=f"{spec.module}.changed", household_id=household_id, payload={})
    for event_type, payload in transitions:
        await emit(session, type=event_type, household_id=household_id, payload=payload)
    return SyncBatchResponse(applied=applied)
