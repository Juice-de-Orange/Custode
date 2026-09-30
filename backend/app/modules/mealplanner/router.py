"""HTTP layer for ``mealplanner`` (KONZEPT §5.4). The manual week plan: read a week, set/clear a
slot. Authoring is member/admin; CSRF on writes. ``week_start`` is normalised to the Monday of its
ISO week so any in-week date maps to the same plan."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.mealplanner import service
from app.modules.mealplanner.filters import normalize_tags
from app.modules.mealplanner.models import MealPlan, MealSlot
from app.modules.mealplanner.nutrition import evaluate_target
from app.modules.mealplanner.schemas import (
    CookTaskResult,
    GenerateResult,
    MealSlotKey,
    MealSlotResponse,
    PersonalSuggestionResponse,
    PrepTaskResult,
    SlotSet,
    WeekNutrition,
    WeekResponse,
)

mealplan_router = APIRouter(prefix="/v1/mealplan", tags=["mealplanner"])

AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _monday(d: date) -> date:
    """The Monday of ``d``'s ISO week — the canonical ``week_start`` key."""
    return d - timedelta(days=d.weekday())


def _week_response(
    plan: MealPlan, slots: list[MealSlot], titles: dict[uuid.UUID, str]
) -> WeekResponse:
    return WeekResponse(
        week_start=plan.week_start,
        slots=[
            MealSlotResponse(
                day_of_week=s.day_of_week,
                slot=s.slot,
                recipe_id=s.recipe_id,
                recipe_title=titles.get(s.recipe_id) if s.recipe_id is not None else None,
                free_text=s.free_text,
                cook_id=s.cook_id,
                note=s.note,
            )
            for s in slots
        ],
    )


@mealplan_router.get("")
async def get_week(
    principal: CurrentPrincipal,
    session: ScopedSession,
    week_start: Annotated[date | None, Query()] = None,
) -> WeekResponse:
    """The plan for the week containing ``week_start`` (default: this week). Created on demand."""
    household_id = _require_household(principal)
    monday = _monday(week_start) if week_start is not None else _monday(date.today())
    plan, slots, titles = await service.get_week(
        session, household_id=household_id, week_start=monday
    )
    absent_days = await service.week_absence_days(
        session, viewer_id=principal.user_id, week_start=monday
    )
    response = _week_response(plan, slots, titles)
    response.absent_days = absent_days
    return response


@mealplan_router.put("/slot", dependencies=[Depends(require_csrf)])
async def set_slot(
    payload: SlotSet,
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
) -> WeekResponse:
    """Set one slot of the given week (recipe or free text, plus cook/note)."""
    household_id = _require_household(principal)
    plan, slots, titles = await service.set_slot(
        session, household_id=household_id, week_start=_monday(week_start), data=payload
    )
    return _week_response(plan, slots, titles)


@mealplan_router.post(
    "/slot/cooked", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def mark_cooked(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    day_of_week: Annotated[int, Query(ge=0, le=6)],
    slot: Annotated[MealSlotKey, Query()],
) -> None:
    """Mark the recipe in a slot as cooked → feeds the recipe's „zuletzt gekocht"-Historie. 422 if
    the slot has no recipe."""
    household_id = _require_household(principal)
    await service.mark_slot_cooked(
        session,
        household_id=household_id,
        week_start=_monday(week_start),
        day_of_week=day_of_week,
        slot_key=slot,
    )


@mealplan_router.get("/suggestion")
async def personal_suggestion(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    slot: Annotated[MealSlotKey, Query()],
    lockout_days: Annotated[int, Query(ge=0, le=365)] = 7,
) -> PersonalSuggestionResponse:
    """Suggest one recipe **to the caller** without touching the shared week plan.

    ``POST /suggest`` looks like a suggestion but writes (``set_slot`` + ``mealplan.updated``).
    This one is read-only, which is precisely why the caller's own wearable recovery signal may
    shape it: the member decides, and only their explicit ``PUT /slot`` changes anything shared
    (S-14 "nur für eigene Vorschläge", ADR-0081 §9). 404 when nothing qualifies."""
    household_id = _require_household(principal)
    suggestion = await service.personal_suggestion(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        week_start=_monday(week_start),
        slot_key=slot,
        lockout_days=lockout_days,
    )
    if suggestion is None:
        raise ProblemException(
            slug="no_candidate", title="Kein passendes Rezept zum Vorschlagen", status=404
        )
    return PersonalSuggestionResponse(
        recipe_id=suggestion.recipe_id,
        title=suggestion.title,
        total_minutes=suggestion.total_minutes,
        reasons=suggestion.reasons,
    )


@mealplan_router.post("/suggest", dependencies=[Depends(require_csrf)])
async def suggest_slot(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    day_of_week: Annotated[int, Query(ge=0, le=6)],
    slot: Annotated[MealSlotKey, Query()],
    lockout_days: Annotated[int, Query(ge=0, le=365)] = 7,
) -> WeekResponse:
    """Auto-fill one slot with the least-recently-cooked eligible recipe („neu würfeln", ADR-0052).
    Skips recipes cooked within ``lockout_days`` and those already planned this week. 422 if none
    qualifies. Returns the refreshed week (like ``PUT /slot``)."""
    household_id = _require_household(principal)
    plan, slots, titles = await service.suggest_slot(
        session,
        household_id=household_id,
        week_start=_monday(week_start),
        day_of_week=day_of_week,
        slot_key=slot,
        lockout_days=lockout_days,
    )
    return _week_response(plan, slots, titles)


@mealplan_router.post("/suggest-week", dependencies=[Depends(require_csrf)])
async def suggest_week(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    slot: Annotated[MealSlotKey, Query()],
    lockout_days: Annotated[int, Query(ge=0, le=365)] = 7,
    target_kcal: Annotated[float | None, Query(ge=0, le=20000)] = None,
    exclude_tag: Annotated[list[str] | None, Query()] = None,
) -> WeekResponse:
    """Fill every empty cell of one meal across the week with distinct recipes. Without
    ``target_kcal``: least-recently-cooked („Woche würfeln", ADR-0052). With ``target_kcal``: the
    recipes whose per-portion kcal is closest to the goal (P6-S12, ADR-0057). ``exclude_tag``
    (repeatable) drops recipes with that tag (allergens/diet, P6-S13). Best-effort — an empty pool
    fills nothing (no 422); existing entries are never overwritten."""
    household_id = _require_household(principal)
    plan, slots, titles = await service.suggest_week(
        session,
        household_id=household_id,
        week_start=_monday(week_start),
        slot_key=slot,
        lockout_days=lockout_days,
        target_kcal=target_kcal,
        exclude_tags=normalize_tags(exclude_tag or []),
    )
    return _week_response(plan, slots, titles)


@mealplan_router.post("/copy", dependencies=[Depends(require_csrf)])
async def copy_week(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    source_week: Annotated[date | None, Query()] = None,
) -> WeekResponse:
    """Copy a plan into ``week_start``'s **empty** cells from ``source_week`` (default: the previous
    week). Non-destructive — existing target entries stay; returns the refreshed target week."""
    household_id = _require_household(principal)
    target = _monday(week_start)
    src = _monday(source_week) if source_week is not None else target - timedelta(days=7)
    plan, slots, titles = await service.copy_week(
        session, household_id=household_id, source_week=src, target_week=target
    )
    return _week_response(plan, slots, titles)


@mealplan_router.post(
    "/slot/cook-task", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_cook_task(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    day_of_week: Annotated[int, Query(ge=0, le=6)],
    slot: Annotated[MealSlotKey, Query()],
) -> CookTaskResult:
    """Create a personal cooking task „Kochen: <Gericht>" from a slot (Synergie S-03, ADR-0053).
    Assigned to the slot's cook or the caller. 422 if the slot has no dish."""
    household_id = _require_household(principal)
    title, assigned_to = await service.create_cook_task(
        session,
        household_id=household_id,
        user_id=principal.user_id,
        week_start=_monday(week_start),
        day_of_week=day_of_week,
        slot_key=slot,
    )
    return CookTaskResult(title=title, assigned_to=assigned_to)


@mealplan_router.post(
    "/slot/prep-task", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_prep_task(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    day_of_week: Annotated[int, Query(ge=0, le=6)],
    slot: Annotated[MealSlotKey, Query()],
) -> PrepTaskResult:
    """Create an advance-prep task „Vorbereiten: <Gericht>" if the slot's recipe needs lead time
    (Synergie S-02, ADR-0055). 422 if the slot has no recipe or nothing to prepare ahead."""
    household_id = _require_household(principal)
    title, assigned_to, hint = await service.create_prep_task(
        session,
        household_id=household_id,
        user_id=principal.user_id,
        week_start=_monday(week_start),
        day_of_week=day_of_week,
        slot_key=slot,
    )
    return PrepTaskResult(title=title, assigned_to=assigned_to, hint=hint)


@mealplan_router.get("/nutrition")
async def week_nutrition(
    principal: CurrentPrincipal,
    session: ScopedSession,
    week_start: Annotated[date | None, Query()] = None,
    target_kcal: Annotated[float | None, Query(ge=0, le=20000)] = None,
) -> WeekNutrition:
    """Summed per-portion macros of the week's planned recipes (P6-S10) — a step toward the
    nutrition-goal automation. Free-text slots are ignored; ``confidence`` flags estimates. With
    ``target_kcal`` the per-portion average is graded ±10% (P6-S11): under/on_target/over."""
    household_id = _require_household(principal)
    monday = _monday(week_start) if week_start is not None else _monday(date.today())
    macros = await service.week_nutrition(session, household_id=household_id, week_start=monday)
    verdict: str | None = None
    if target_kcal is not None and macros.meals_counted > 0:
        avg = round(macros.kcal / macros.meals_counted, 1)
        verdict = evaluate_target(avg, target_kcal)
    return WeekNutrition(
        kcal=macros.kcal,
        protein_g=macros.protein_g,
        fat_g=macros.fat_g,
        carbs_g=macros.carbs_g,
        meals_counted=macros.meals_counted,
        confidence=macros.confidence,
        target_kcal=target_kcal,
        verdict=verdict,
    )


@mealplan_router.post("/to-shopping", dependencies=[Depends(require_csrf)])
async def to_shopping(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
) -> GenerateResult:
    """Add the week's recipe ingredients to the default shopping list (KONZEPT §5.5). Idempotent —
    re-running upserts the same items, so it never duplicates."""
    household_id = _require_household(principal)
    added = await service.generate_shopping(
        session,
        household_id=household_id,
        user_id=principal.user_id,
        week_start=_monday(week_start),
    )
    return GenerateResult(added=added)


@mealplan_router.delete("/slot", dependencies=[Depends(require_csrf)])
async def clear_slot(
    principal: AuthorPrincipal,
    session: ScopedSession,
    week_start: Annotated[date, Query()],
    day_of_week: Annotated[int, Query(ge=0, le=6)],
    slot: Annotated[MealSlotKey, Query()],
) -> WeekResponse:
    """Clear one slot of the given week."""
    household_id = _require_household(principal)
    plan, slots, titles = await service.clear_slot(
        session,
        household_id=household_id,
        week_start=_monday(week_start),
        day_of_week=day_of_week,
        slot_key=slot,
    )
    return _week_response(plan, slots, titles)
