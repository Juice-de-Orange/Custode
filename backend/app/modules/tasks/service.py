"""tasks use-cases. Services own no transaction control here — they run on the request's
RLS-scoped session (``household_id = app.household_id``); the dependency commits the unit of work.

Write path = PATCH + If-Match (ADR-0034): ``version`` is the ETag, bumped by the shared trigger.
Instance completion is a server-authoritative state transition (``open -> done``); P4-S1 books NO
points — it only emits ``task.completed`` so a later ledger slice can react (KONZEPT §5.9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.economy import api as economy_api
from app.modules.tasks.decay import effective_points
from app.modules.tasks.models import Room, TaskInstance, TaskTemplate
from app.modules.tasks.schemas import TaskInstanceCreate, TaskTemplateCreate, TaskTemplateUpdate

# --- Templates ---------------------------------------------------------------


async def create_template(
    session: AsyncSession, *, household_id: uuid.UUID, data: TaskTemplateCreate
) -> TaskTemplate:
    """Create a task template. Emits ``task.created``."""
    template = TaskTemplate(
        household_id=household_id,
        title=data.title,
        description=data.description,
        points=data.points,
        duration_est_minutes=data.duration_est_minutes,
        outdoor=data.outdoor,
        rotation=data.rotation,
        room_id=data.room_id,
    )
    session.add(template)
    await emit(
        session,
        type="task.created",
        household_id=household_id,
        payload={"template_id": str(template.id)},
    )
    await session.flush()
    return template


async def list_templates(session: AsyncSession) -> list[TaskTemplate]:
    """The active household's templates (RLS-scoped). Soft-deleted rows excluded."""
    rows = await session.scalars(
        select(TaskTemplate).where(TaskTemplate.deleted_at.is_(None)).order_by(TaskTemplate.title)
    )
    return list(rows)


async def get_template(session: AsyncSession, *, template_id: uuid.UUID) -> TaskTemplate:
    """One template of the active household (RLS hides other households -> 404)."""
    template = await session.get(TaskTemplate, template_id)
    if template is None or template.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Vorlage nicht gefunden", status=404)
    return template


async def update_template(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    template_id: uuid.UUID,
    expected_version: int,
    data: TaskTemplateUpdate,
) -> TaskTemplate:
    """Patch a template under optimistic concurrency (``expected_version`` = If-Match). Emits
    ``task.updated``. Existing instances keep their snapshot (title/points are not rewritten)."""
    template = await get_template(session, template_id=template_id)
    if template.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Vorlage zwischenzeitlich geändert", status=412
        )
    if data.title is not None:
        template.title = data.title
    if data.description is not None:
        template.description = data.description
    if data.points is not None:
        template.points = data.points
    if data.duration_est_minutes is not None:
        template.duration_est_minutes = data.duration_est_minutes
    if data.outdoor is not None:
        template.outdoor = data.outdoor
    if data.rotation is not None:
        template.rotation = data.rotation
    if data.room_id is not None:
        template.room_id = data.room_id
    await emit(
        session,
        type="task.updated",
        household_id=household_id,
        payload={"template_id": str(template_id)},
    )
    await session.flush()
    await session.refresh(template, attribute_names=["version", "updated_at"])
    return template


async def delete_template(
    session: AsyncSession, *, household_id: uuid.UUID, template_id: uuid.UUID
) -> None:
    """Soft-delete a template. Emits ``task.deleted``. Instances are NOT cascade-deleted — their
    history (and ``template_id`` link) is preserved for the future ledger/fairness account."""
    template = await get_template(session, template_id=template_id)
    template.deleted_at = datetime.now(UTC)
    await emit(
        session,
        type="task.deleted",
        household_id=household_id,
        payload={"template_id": str(template_id)},
    )


# --- Instances ---------------------------------------------------------------


async def create_instance(
    session: AsyncSession, *, household_id: uuid.UUID, data: TaskInstanceCreate
) -> TaskInstance:
    """Create an instance — from a template (snapshot title/points) or ad-hoc (title required).
    Emits ``task_instance.created``. The instance starts ``open``."""
    title = data.title
    points = 0
    if data.template_id is not None:
        template = await get_template(session, template_id=data.template_id)
        title = data.title or template.title  # explicit override allowed, else snapshot
        points = template.points
    if not title:
        raise ProblemException(
            slug="title_required",
            title="Titel erforderlich (Template oder Titel angeben)",
            status=422,
        )
    instance = TaskInstance(
        household_id=household_id,
        template_id=data.template_id,
        title=title,
        points=points,
        assigned_to=data.assigned_to,
        due_at=data.due_at,
        room_id=data.room_id,
        status="open",
    )
    session.add(instance)
    await emit(
        session,
        type="task_instance.created",
        household_id=household_id,
        payload={
            "instance_id": str(instance.id),
            "template_id": str(data.template_id) if data.template_id else None,
        },
    )
    await session.flush()
    return instance


async def create_personal_task(
    session: AsyncSession, *, household_id: uuid.UUID, title: str, assigned_to: uuid.UUID
) -> TaskInstance:
    """Create a personal ad-hoc task (points 0, KONZEPT §5.6/5.9) — the public, primitive-args seam
    for cross-module callers (e.g. ``capture`` confirming a Zuruf). Wraps ``create_instance`` so
    they need not import the tasks schemas."""
    return await create_instance(
        session,
        household_id=household_id,
        data=TaskInstanceCreate(title=title, assigned_to=assigned_to),
    )


async def create_armed_task(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    title: str,
    assigned_to: uuid.UUID,
    on_item_checked: uuid.UUID,
) -> TaskInstance:
    """Create an ``armed`` action-chain follow-up (KONZEPT §5.17): a personal, points-0 task, not
    yet actionable and excluded from the default open list. A matching ``shopping.item.checked``
    flips it to ``open`` (``activate_on_item_checked``). Used by capture to wire a Zuruf chain."""
    instance = TaskInstance(
        household_id=household_id,
        title=title,
        points=0,
        assigned_to=assigned_to,
        status="armed",
        activation_json={"on_item_checked": str(on_item_checked)},
    )
    session.add(instance)
    await emit(
        session,
        type="task_instance.created",
        household_id=household_id,
        payload={"instance_id": str(instance.id), "template_id": None},
    )
    await session.flush()
    return instance


async def activate_on_item_checked(
    session: AsyncSession, *, household_id: uuid.UUID, item_id: uuid.UUID
) -> int:
    """Activate every armed follow-up whose ``activation_json.on_item_checked`` matches ``item_id``
    (KONZEPT §5.17): ``armed -> open``. Idempotent (an already-open task no longer matches the armed
    filter). Emits ``task.updated`` per activated instance so clients refresh. Returns the count."""
    rows = await session.scalars(
        select(TaskInstance).where(
            TaskInstance.status == "armed",
            TaskInstance.deleted_at.is_(None),
            TaskInstance.activation_json["on_item_checked"].astext == str(item_id),
        )
    )
    activated = 0
    for instance in rows:
        instance.status = "open"
        await emit(session, type="task.updated", household_id=household_id, payload={})
        activated += 1
    if activated:
        await session.flush()
    return activated


async def list_instances(
    session: AsyncSession, *, status: str | None = "open"
) -> list[TaskInstance]:
    """The active household's instances (RLS-scoped), optionally filtered by status (default
    ``open``; pass ``None`` for all). Soft-deleted rows excluded."""
    stmt = select(TaskInstance).where(TaskInstance.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(TaskInstance.status == status)
    rows = await session.scalars(stmt.order_by(TaskInstance.due_at.is_(None), TaskInstance.due_at))
    return list(rows)


async def get_instance(session: AsyncSession, *, instance_id: uuid.UUID) -> TaskInstance:
    """One instance of the active household (RLS hides other households -> 404)."""
    instance = await session.get(TaskInstance, instance_id)
    if instance is None or instance.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Aufgabe nicht gefunden", status=404)
    return instance


async def instance_status(session: AsyncSession, *, instance_id: uuid.UUID) -> str | None:
    """``open`` / ``done`` / ``expired``, or ``None`` when the instance is gone or tombstoned.

    Exists so a caller can **ask** instead of catching: ``get_instance`` answers "not there" with a
    404 ``ProblemException``, and a caller that turns that into control flow is deciding on an
    HTTP status — a representation of the question, not the question. The exit path needs the real
    answer (BUGLOG 2026-08-03): it must know whether the work was delivered before it unwinds a
    trade, and it must not die because the task meanwhile vanished."""
    instance = await session.get(TaskInstance, instance_id)
    if instance is None or instance.deleted_at is not None:
        return None
    return instance.status


async def complete_instance(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    instance_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_version: int,
) -> TaskInstance:
    """Complete an instance: state transition ``open -> done``, server-stamping ``done_by``/
    ``done_at`` (not client-writable). Guarded by If-Match (412 stale) AND a status check (409 if
    not ``open``) so a double-submit cannot emit ``task.completed`` twice — the most important
    correctness property of the slice (a later ledger would otherwise double-book). Emits
    ``task.completed`` carrying ``points``/``done_by`` as the contract seam for the ledger slice."""
    instance = await get_instance(session, instance_id=instance_id)
    if instance.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Aufgabe zwischenzeitlich geändert", status=412
        )
    if instance.status != "open":
        raise ProblemException(slug="invalid_state", title="Aufgabe ist nicht offen", status=409)
    now = datetime.now(UTC)
    instance.status = "done"
    instance.done_at = now
    instance.done_by = user_id
    # Soft value-decay (KONZEPT §5.9): an overdue task is worth less (-10%/day overdue, floor 50%).
    # The effective amount is what gets booked + recorded on the instance.
    awarded = effective_points(instance.points, instance.due_at, now)
    instance.awarded_points = awarded
    # Credit the points ledger synchronously in this same transaction (ADR-0035): atomic with the
    # state change, exactly-once via the 409 guard above, balance visible immediately. No-op at 0.
    await economy_api.credit_task_completion(
        session,
        household_id=household_id,
        member_id=user_id,
        amount=awarded,
        instance_id=instance_id,
    )
    await emit(
        session,
        type="task.completed",
        household_id=household_id,
        payload={
            "instance_id": str(instance_id),
            "template_id": str(instance.template_id) if instance.template_id else None,
            "points": awarded,
            "done_by": str(user_id),
        },
    )
    await session.flush()
    await session.refresh(instance, attribute_names=["version", "updated_at"])
    return instance


# --- Rooms + heatmap (KONZEPT §5.9/§5.8) -------------------------------------


async def create_room(
    session: AsyncSession, *, household_id: uuid.UUID, name: str, icon: str | None, decay_days: int
) -> Room:
    """Create a room (admin). Emits ``task.updated`` (rooms ride the tasks SSE entity)."""
    room = Room(household_id=household_id, name=name, icon=icon, decay_days=decay_days)
    session.add(room)
    await emit(session, type="task.updated", household_id=household_id, payload={"room": True})
    await session.flush()
    return room


async def list_rooms(session: AsyncSession) -> list[Room]:
    rows = await session.scalars(select(Room).where(Room.deleted_at.is_(None)).order_by(Room.name))
    return list(rows)


async def get_room(session: AsyncSession, *, room_id: uuid.UUID) -> Room:
    room = await session.get(Room, room_id)
    if room is None or room.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Raum nicht gefunden", status=404)
    return room


async def update_room(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    room_id: uuid.UUID,
    expected_version: int,
    name: str | None,
    icon: str | None,
    decay_days: int | None,
) -> Room:
    """Patch a room under optimistic concurrency (admin)."""
    room = await get_room(session, room_id=room_id)
    if room.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Raum zwischenzeitlich geändert", status=412
        )
    if name is not None:
        room.name = name
    if icon is not None:
        room.icon = icon
    if decay_days is not None:
        room.decay_days = decay_days
    await emit(session, type="task.updated", household_id=household_id, payload={"room": True})
    await session.flush()
    await session.refresh(room, attribute_names=["version", "updated_at"])
    return room


async def delete_room(
    session: AsyncSession, *, household_id: uuid.UUID, room_id: uuid.UUID
) -> None:
    """Soft-delete a room (admin). Templates keep ``room_id`` (dangling) until reassigned — the
    heatmap only lists non-deleted rooms, so a deleted room simply disappears."""
    room = await get_room(session, room_id=room_id)
    room.deleted_at = datetime.now(UTC)
    await emit(session, type="task.updated", household_id=household_id, payload={"room": True})


async def room_last_done(session: AsyncSession) -> list[tuple[Room, datetime | None]]:
    """Each non-deleted room with the most recent completion among the tasks that belong to it
    (NULL if never). A task's room is its **own** ``room_id`` if set, else its template's (S-13);
    the heatmap status (green/amber/red) is computed from this + ``decay_days``."""
    effective_room = func.coalesce(TaskInstance.room_id, TaskTemplate.room_id)
    done = (
        select(
            effective_room.label("room_id"),
            TaskInstance.done_at.label("done_at"),
        )
        .select_from(TaskInstance)
        .outerjoin(TaskTemplate, TaskTemplate.id == TaskInstance.template_id)
        .where(TaskInstance.status == "done", TaskInstance.deleted_at.is_(None))
        .subquery()
    )
    rows = await session.execute(
        select(Room, func.max(done.c.done_at))
        .select_from(Room)
        .outerjoin(done, done.c.room_id == Room.id)
        .where(Room.deleted_at.is_(None))
        .group_by(Room.id)
        .order_by(Room.name)
    )
    return [(room, last) for room, last in rows.all()]


# --- Cross-module helpers (exported via api.py) ------------------------------


async def release_assignments_of(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID
) -> int:
    """Offene Aufgaben einer ausscheidenden Person in den Pool zurückgeben (KONZEPT §5.1).

    ``assigned_to`` ist eine nackte ``user_id`` ohne Fremdschlüssel — bleibt sie stehen, zeigt die
    Aufgabe dauerhaft auf jemanden, der den Haushalt verlassen hat: sie taucht in keiner Liste des
    Zuständigen mehr auf, blockiert aber die Rotation und sieht für die Übrigen aus wie „vergeben".
    ``NULL`` heißt „niemand zugewiesen" und ist der Zustand, den die Rotation kennt.

    Nur **offene** Instanzen: eine erledigte Aufgabe ist Historie, und wer sie erledigt hat, gehört
    zur Wahrheit über den Haushalt (``done_by`` bleibt entsprechend unberührt). Idempotent.
    """
    result = await session.execute(
        update(TaskInstance)
        .where(
            TaskInstance.assigned_to == member_id,
            TaskInstance.status == "open",
            TaskInstance.deleted_at.is_(None),
        )
        .values(assigned_to=None)
        .returning(TaskInstance.id)
    )
    released = len(result.scalars().all())
    if released:
        await emit(session, type="task.updated", household_id=household_id, payload={})
    return released


async def reassign_instance(
    session: AsyncSession, *, household_id: uuid.UUID, instance_id: uuid.UUID, assignee: uuid.UUID
) -> TaskInstance:
    """Reassign an OPEN instance to another member (marketplace accept, KONZEPT §5.10). 409 if the
    instance is no longer open. Emits ``task.updated``."""
    instance = await get_instance(session, instance_id=instance_id)
    if instance.status != "open":
        raise ProblemException(slug="invalid_state", title="Aufgabe ist nicht offen", status=409)
    instance.assigned_to = assignee
    await emit(
        session,
        type="task.updated",
        household_id=household_id,
        payload={"instance_id": str(instance_id)},
    )
    await session.flush()
    return instance


async def count_open_tasks(
    session: AsyncSession, *, household_id: uuid.UUID, now: datetime
) -> tuple[int, int]:
    """``(open, overdue)`` counts of a household's task instances, for the weekly digest (P8-S6).
    Filters ``household_id`` **explicitly** — the digest runs under the maint role (which sees all
    households), so an RLS scope cannot be relied on. ``overdue`` = still open with a ``due_at`` in
    the past."""
    base = (
        select(func.count())
        .select_from(TaskInstance)
        .where(
            TaskInstance.household_id == household_id,
            TaskInstance.status == "open",
            TaskInstance.deleted_at.is_(None),
        )
    )
    open_count = await session.scalar(base) or 0
    overdue = base.where(TaskInstance.due_at.is_not(None), TaskInstance.due_at < now)
    overdue_count = await session.scalar(overdue) or 0
    return int(open_count), int(overdue_count)
