"""HTTP layer for ``tasks`` (KONZEPT §5.9). Thin: validate -> service -> response. Tasks are
household-scoped (RLS) with PATCH + If-Match (ADR-0034); template GET/POST/PATCH carry an ETag
(= version), as does an instance (its ETag guards the complete action).

Authoring templates is admin-only (KONZEPT §5.9 "Punktwerte setzt der Admin je Template"); creating
instances is member+; completing is open to any household member incl. children (gamification)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import (
    AdminPrincipal,
    CurrentPrincipal,
    ScopedSession,
    require_role,
)
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.tasks import service
from app.modules.tasks.heatmap import room_status
from app.modules.tasks.models import Room, TaskInstance, TaskTemplate
from app.modules.tasks.schemas import (
    RoomCreate,
    RoomHeatmapEntry,
    RoomResponse,
    RoomUpdate,
    TaskInstanceCreate,
    TaskInstanceResponse,
    TaskTemplateCreate,
    TaskTemplateResponse,
    TaskTemplateSummary,
    TaskTemplateUpdate,
)

tasks_router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

# Member+ may create instances; completion additionally allows children (they earn by doing).
MemberPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]
DoerPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member, Role.child))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _template_response(t: TaskTemplate) -> TaskTemplateResponse:
    return TaskTemplateResponse(
        id=t.id,
        title=t.title,
        description=t.description,
        points=t.points,
        duration_est_minutes=t.duration_est_minutes,
        outdoor=t.outdoor,
        rotation=t.rotation,
        room_id=t.room_id,
        version=t.version,
    )


def _instance_response(i: TaskInstance) -> TaskInstanceResponse:
    return TaskInstanceResponse(
        id=i.id,
        template_id=i.template_id,
        title=i.title,
        points=i.points,
        assigned_to=i.assigned_to,
        due_at=i.due_at,
        status=i.status,
        done_at=i.done_at,
        done_by=i.done_by,
        awarded_points=i.awarded_points,
        room_id=i.room_id,
        version=i.version,
    )


# --- Templates ---------------------------------------------------------------


@tasks_router.get("/templates")
async def list_templates(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[TaskTemplateSummary]:
    templates = await service.list_templates(session)
    return [
        TaskTemplateSummary(
            id=t.id,
            title=t.title,
            points=t.points,
            outdoor=t.outdoor,
            rotation=t.rotation,
            room_id=t.room_id,
        )
        for t in templates
    ]


@tasks_router.post(
    "/templates", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_template(
    payload: TaskTemplateCreate,
    principal: AdminPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskTemplateResponse:
    household_id = _require_household(principal)
    template = await service.create_template(session, household_id=household_id, data=payload)
    response.headers["ETag"] = f'"{template.version}"'
    return _template_response(template)


@tasks_router.get("/templates/{template_id}")
async def get_template(
    template_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskTemplateResponse:
    template = await service.get_template(session, template_id=template_id)
    response.headers["ETag"] = f'"{template.version}"'
    return _template_response(template)


@tasks_router.patch("/templates/{template_id}", dependencies=[Depends(require_csrf)])
async def update_template(
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    request: Request,
    principal: AdminPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskTemplateResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    template = await service.update_template(
        session,
        household_id=household_id,
        template_id=template_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{template.version}"'
    return _template_response(template)


@tasks_router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_template(
    template_id: uuid.UUID, principal: AdminPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_template(session, household_id=household_id, template_id=template_id)


# --- Instances ---------------------------------------------------------------


@tasks_router.get("/instances")
async def list_instances(
    principal: CurrentPrincipal,
    session: ScopedSession,
    status_filter: Annotated[
        Literal["open", "done", "expired", "armed", "all"], Query(alias="status")
    ] = "open",
) -> list[TaskInstanceResponse]:
    instances = await service.list_instances(
        session, status=None if status_filter == "all" else status_filter
    )
    return [_instance_response(i) for i in instances]


@tasks_router.post(
    "/instances", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_instance(
    payload: TaskInstanceCreate,
    principal: MemberPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskInstanceResponse:
    household_id = _require_household(principal)
    instance = await service.create_instance(session, household_id=household_id, data=payload)
    response.headers["ETag"] = f'"{instance.version}"'
    return _instance_response(instance)


@tasks_router.get("/instances/{instance_id}")
async def get_instance(
    instance_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskInstanceResponse:
    instance = await service.get_instance(session, instance_id=instance_id)
    response.headers["ETag"] = f'"{instance.version}"'
    return _instance_response(instance)


@tasks_router.post("/instances/{instance_id}/complete", dependencies=[Depends(require_csrf)])
async def complete_instance(
    instance_id: uuid.UUID,
    request: Request,
    principal: DoerPrincipal,
    session: ScopedSession,
    response: Response,
) -> TaskInstanceResponse:
    """Mark an instance done (``open -> done``). If-Match-guarded; 409 if not open. Emits
    ``task.completed`` (the seam a later points-ledger slice subscribes to)."""
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    instance = await service.complete_instance(
        session,
        household_id=household_id,
        instance_id=instance_id,
        user_id=principal.user_id,
        expected_version=expected,
    )
    response.headers["ETag"] = f'"{instance.version}"'
    return _instance_response(instance)


# --- Rooms + heatmap ---------------------------------------------------------


def _room_response(r: Room) -> RoomResponse:
    return RoomResponse(
        id=r.id, name=r.name, icon=r.icon, decay_days=r.decay_days, version=r.version
    )


@tasks_router.get("/heatmap")
async def room_heatmap(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[RoomHeatmapEntry]:
    """Per-room freshness (green/amber/red) computed from each room's last task completion and its
    ``decay_days`` (KONZEPT §5.9). Never stored — always derived."""
    _require_household(principal)
    now = datetime.now(UTC)
    rows = await service.room_last_done(session)
    return [
        RoomHeatmapEntry(
            room_id=room.id,
            name=room.name,
            icon=room.icon,
            decay_days=room.decay_days,
            last_done=last_done,
            status=room_status(last_done, room.decay_days, now),
        )
        for room, last_done in rows
    ]


@tasks_router.get("/rooms")
async def list_rooms(principal: CurrentPrincipal, session: ScopedSession) -> list[RoomResponse]:
    _require_household(principal)
    return [_room_response(r) for r in await service.list_rooms(session)]


@tasks_router.post(
    "/rooms", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_room(
    payload: RoomCreate, principal: AdminPrincipal, session: ScopedSession, response: Response
) -> RoomResponse:
    household_id = _require_household(principal)
    room = await service.create_room(
        session,
        household_id=household_id,
        name=payload.name,
        icon=payload.icon,
        decay_days=payload.decay_days,
    )
    response.headers["ETag"] = f'"{room.version}"'
    return _room_response(room)


@tasks_router.patch("/rooms/{room_id}", dependencies=[Depends(require_csrf)])
async def update_room(
    room_id: uuid.UUID,
    payload: RoomUpdate,
    request: Request,
    principal: AdminPrincipal,
    session: ScopedSession,
    response: Response,
) -> RoomResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    room = await service.update_room(
        session,
        household_id=household_id,
        room_id=room_id,
        expected_version=expected,
        name=payload.name,
        icon=payload.icon,
        decay_days=payload.decay_days,
    )
    response.headers["ETag"] = f'"{room.version}"'
    return _room_response(room)


@tasks_router.delete(
    "/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_room(
    room_id: uuid.UUID, principal: AdminPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_room(session, household_id=household_id, room_id=room_id)
