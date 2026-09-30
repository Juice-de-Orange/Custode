"""capture use-cases — der Zuruf-Eingang + Inbox-Triage (KONZEPT §5.17). Services run on the
request's RLS-scoped session; the dependency commits the unit of work.

Beim Zuruf zerlegt der offline Regel-Parser den Freitext in einen Vorschlag und legt eine
``proposed``-Capture an. Beim Bestätigen wird der Vorschlag **serverseitig über die öffentlichen
Ziel-Modul-APIs angewandt** (ADR-0038): ein Posten via ``shopping.api`` über den Sync-Batch (mit
deterministischer ``client_op_id`` → idempotent, kein zweiter Schreibpfad), ein persönlicher Task
via ``tasks.api.create_personal_task`` (punktelos). Cross-Modul nur über ``shopping.api`` +
``tasks.api`` — einseitig, kein Zyklus."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.ports.llm import LlmPort
from app.kernel.sync.schemas import SyncOp
from app.modules.capture.enrich import ENRICH_SCHEMA, build_prompt, merge_enrichment
from app.modules.capture.models import Capture
from app.modules.capture.parser import parse_capture
from app.modules.capture.schemas import ParsedProposal
from app.modules.shopping import api as shopping_api
from app.modules.tasks import api as tasks_api

# Namespaces for the deterministic op ids a confirm synthesises (idempotent re-confirm).
_ITEM_NS = uuid.uuid5(uuid.NAMESPACE_URL, "custode:capture:shopping-item")


def _proposal(capture: Capture) -> ParsedProposal:
    return ParsedProposal.model_validate(capture.proposal_json)


async def get_capture(session: AsyncSession, *, capture_id: uuid.UUID) -> Capture:
    capture = await session.get(Capture, capture_id)
    if capture is None or capture.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Zuruf nicht gefunden", status=404)
    return capture


async def create_capture(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    raw_text: str,
    llm: LlmPort,
) -> Capture:
    """Parse a free-text Zuruf and store it as a ``proposed`` capture. The deterministic parse is
    the base path; an optional LLM (Ollama, else the Null adapter) refines free-text fields only —
    routing (``target``/``follow_up``) stays deterministic (ADR-0068). Emits ``capture.created``."""
    base = parse_capture(raw_text)
    llm_result = await llm.extract(prompt=build_prompt(raw_text), schema=ENRICH_SCHEMA)
    proposal = merge_enrichment(base, llm_result)
    capture = Capture(
        household_id=household_id,
        member_id=member_id,
        raw_text=raw_text,
        tags=list(proposal.tags),
        status="proposed",
        proposal_json=proposal.model_dump(),
    )
    session.add(capture)
    await session.flush()
    await emit(session, type="capture.created", household_id=household_id, payload={})
    return capture


async def list_inbox(session: AsyncSession, *, member_id: uuid.UUID) -> list[Capture]:
    """The caller's own open (``proposed``) captures — the triage inbox (RLS-scoped)."""
    rows = await session.scalars(
        select(Capture)
        .where(
            Capture.member_id == member_id,
            Capture.status == "proposed",
            Capture.deleted_at.is_(None),
        )
        .order_by(Capture.created_at.desc())
    )
    return list(rows)


async def confirm_capture(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID, capture_id: uuid.UUID
) -> Capture:
    """Apply a proposed capture's proposal and mark it ``confirmed`` (emits ``capture.processed``).
    404 if it is not the caller's own; 409 if it is not ``proposed`` or has no actionable target."""
    capture = await get_capture(session, capture_id=capture_id)
    if capture.member_id != member_id:
        raise ProblemException(slug="not_found", title="Zuruf nicht gefunden", status=404)
    if capture.status != "proposed":
        raise ProblemException(slug="invalid_state", title="Zuruf nicht offen", status=409)
    proposal = _proposal(capture)

    if proposal.target == "shopping":
        list_id = await shopping_api.ensure_default_list(
            session, household_id=household_id, user_id=member_id
        )
        item_id = uuid.uuid5(_ITEM_NS, f"item:{capture_id}")
        fields: dict[str, object] = {
            "list_id": str(list_id),
            "label": proposal.label,
            "source": "zuruf",
        }
        if proposal.qty is not None:
            fields["qty"] = proposal.qty
        if proposal.unit is not None:
            fields["unit"] = proposal.unit
        await shopping_api.apply_shopping_batch(
            session,
            household_id=household_id,
            user_id=member_id,
            ops=[
                SyncOp(
                    client_op_id=uuid.uuid5(_ITEM_NS, f"op:{capture_id}"),
                    entity="shopping_item",
                    id=item_id,
                    op="upsert",
                    fields=fields,
                )
            ],
        )
        # Action chain (Deo-Fall, KONZEPT §5.17): arm a follow-up task on this item being checked.
        if proposal.follow_up is not None:
            await tasks_api.create_armed_task(
                session,
                household_id=household_id,
                title=proposal.follow_up.label,
                assigned_to=member_id,
                on_item_checked=item_id,
            )
    elif proposal.target == "task":
        await tasks_api.create_personal_task(
            session, household_id=household_id, title=proposal.label, assigned_to=member_id
        )
    else:
        # note (no notes module before Phase 7) or „Unsortiert" — nothing to create yet.
        raise ProblemException(
            slug="no_target", title="Kein Ziel zum Anlegen (bitte zuordnen)", status=409
        )

    capture.status = "confirmed"
    await emit(session, type="capture.processed", household_id=household_id, payload={})
    await session.flush()
    return capture


async def dismiss_capture(
    session: AsyncSession, *, member_id: uuid.UUID, capture_id: uuid.UUID
) -> Capture:
    """Discard a proposed capture (``dismissed``). 404 if not the caller's own."""
    capture = await get_capture(session, capture_id=capture_id)
    if capture.member_id != member_id:
        raise ProblemException(slug="not_found", title="Zuruf nicht gefunden", status=404)
    if capture.status != "proposed":
        raise ProblemException(slug="invalid_state", title="Zuruf nicht offen", status=409)
    capture.status = "dismissed"
    await emit(session, type="capture.processed", household_id=capture.household_id, payload={})
    await session.flush()
    return capture
