"""mealplanner use-cases (KONZEPT §5.4). Runs on the request's RLS-scoped session. A slot's recipe
is stored as a bare ``recipe_id`` and resolved to a title through ``recipes.api`` (module boundary —
mealplanner never reads the recipes table directly). Emits ``mealplan.updated`` on any change (the
seam the shopping-list regeneration will consume in a later slice)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.sync.schemas import SyncOp
from app.modules.calendar import api as calendar_api
from app.modules.mealplanner.absence import absence_weekdays
from app.modules.mealplanner.filters import has_excluded_tag
from app.modules.mealplanner.models import MealPlan, MealSlot
from app.modules.mealplanner.nutrition import MacroSum, sum_macros
from app.modules.mealplanner.prep import needs_prep
from app.modules.mealplanner.schemas import SlotSet
from app.modules.mealplanner.suggest import (
    Candidate,
    pick_for_target,
    pick_least_recently_cooked,
    pick_quickest,
    suggest_many,
)
from app.modules.recipes import api as recipes_api
from app.modules.shopping import api as shopping_api
from app.modules.tasks import api as tasks_api
from app.modules.wearables import api as wearables_api

# Deterministic namespace so re-generating the same week upserts the same items (idempotent).
_SHOP_NS = uuid.uuid5(uuid.NAMESPACE_URL, "custode:mealplan:shopping-item")


async def _get_or_create_plan(
    session: AsyncSession, *, household_id: uuid.UUID, week_start: date
) -> MealPlan:
    plan = await session.scalar(
        select(MealPlan).where(MealPlan.week_start == week_start, MealPlan.deleted_at.is_(None))
    )
    if plan is None:
        plan = MealPlan(household_id=household_id, week_start=week_start)
        session.add(plan)
        await session.flush()
    return plan


async def _recipe_titles(session: AsyncSession, recipe_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Resolve recipe ids to titles via recipes.api (RLS-scoped). Missing/deleted recipes are
    simply absent from the map (the slot then shows no title)."""
    titles: dict[uuid.UUID, str] = {}
    for recipe in await recipes_api.list_recipes(session):
        if recipe.id in recipe_ids:
            titles[recipe.id] = recipe.title
    return titles


async def get_week(
    session: AsyncSession, *, household_id: uuid.UUID, week_start: date
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """The plan for ``week_start`` (created on demand), its filled slots, and a recipe-id->title map
    for rendering. Read-only — a fresh week simply has no slots yet."""
    plan = await _get_or_create_plan(session, household_id=household_id, week_start=week_start)
    slots = list(
        await session.scalars(
            select(MealSlot).where(MealSlot.plan_id == plan.id, MealSlot.deleted_at.is_(None))
        )
    )
    titles = await _recipe_titles(session, {s.recipe_id for s in slots if s.recipe_id is not None})
    return plan, slots, titles


async def week_absence_days(
    session: AsyncSession, *, viewer_id: uuid.UUID, week_start: date
) -> list[int]:
    """The weekday indices (0-6) the viewer is away during ``week_start``'s week (Synergie S-01,
    ADR-0054). Reads the expanded absence intervals via ``calendar.api`` (one-way) and maps them
    with the pure ``absence_weekdays``. Empty when the calendar has no overlapping absence."""
    frm = datetime.combine(week_start, time.min, tzinfo=UTC)
    to = frm + timedelta(days=7)
    intervals = await calendar_api.list_absence_intervals(
        session, viewer_id=viewer_id, frm=frm, to=to
    )
    return absence_weekdays(intervals, week_start=week_start)


async def set_slot(
    session: AsyncSession, *, household_id: uuid.UUID, week_start: date, data: SlotSet
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """Upsert one slot (recipe **or** free text, plus cook/note). Emits ``mealplan.updated`` and
    returns the refreshed week."""
    plan = await _get_or_create_plan(session, household_id=household_id, week_start=week_start)
    slot = await session.scalar(
        select(MealSlot).where(
            MealSlot.plan_id == plan.id,
            MealSlot.day_of_week == data.day_of_week,
            MealSlot.slot == data.slot,
            MealSlot.deleted_at.is_(None),
        )
    )
    if slot is None:
        slot = MealSlot(
            household_id=household_id,
            plan_id=plan.id,
            day_of_week=data.day_of_week,
            slot=data.slot,
        )
        session.add(slot)
    slot.recipe_id = data.recipe_id
    slot.free_text = data.free_text
    slot.cook_id = data.cook_id
    slot.note = data.note
    await emit(session, type="mealplan.updated", household_id=household_id, payload={})
    await session.flush()
    return await get_week(session, household_id=household_id, week_start=week_start)


async def suggest_slot(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    week_start: date,
    day_of_week: int,
    slot_key: str,
    lockout_days: int,
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """Auto-fill one slot with the least-recently-cooked eligible recipe („neu würfeln", ADR-0052).

    Candidates come from ``recipes.api`` (RLS-scoped, carries ``last_cooked_at`` since P6-S3);
    recipes already planned **anywhere this week** (incl. the slot's current occupant) are excluded
    so the roll brings variety and never returns the same recipe. 422 if nothing qualifies. The pick
    is written through the normal ``set_slot`` path — one write path; emits ``mealplan.updated``."""
    _, slots, _ = await get_week(session, household_id=household_id, week_start=week_start)
    exclude_ids = frozenset(s.recipe_id for s in slots if s.recipe_id is not None)
    recipes = await recipes_api.list_recipes(session)
    candidates = [Candidate(id=r.id, last_cooked_at=r.last_cooked_at) for r in recipes]
    pick = pick_least_recently_cooked(
        candidates, now=datetime.now(UTC), lockout_days=lockout_days, exclude_ids=exclude_ids
    )
    if pick is None:
        raise ProblemException(
            slug="no_candidate", title="Kein passendes Rezept zum Vorschlagen", status=422
        )
    data = SlotSet(day_of_week=day_of_week, slot=slot_key, recipe_id=pick)
    return await set_slot(session, household_id=household_id, week_start=week_start, data=data)


@dataclass(frozen=True)
class PersonalSuggestion:
    """A suggestion made TO one member — deliberately not a write.

    ``reasons`` are machine-readable codes (the web translates them), mirroring the scheduling
    engine. This is the whole point of the shape: because nothing is persisted, the member's own
    recovery signal may shape it without a health state ever determining a shared household
    record (ADR-0081 §9)."""

    recipe_id: uuid.UUID
    title: str
    total_minutes: int | None
    reasons: list[str]


async def personal_suggestion(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    week_start: date,
    slot_key: str,
    lockout_days: int,
    now: datetime | None = None,
) -> PersonalSuggestion | None:
    """Suggest one recipe **to the caller** without touching the shared week plan.

    ``suggest_slot`` looks like a suggestion but is a write path (``set_slot`` +
    ``mealplan.updated``) — feeding a member's Art.-9 recovery signal into it would let their
    health state determine a household record, which S-14 rules out ("nur für eigene
    Vorschläge"). This endpoint is the honest home for that signal: it returns a proposal, the
    member decides, and only their explicit ``PUT /slot`` changes anything shared.

    Same eligibility as the roll (repeat-lockout, nothing already planned this week). With a
    low-recovery signal the ordering flips from least-recently-cooked to least-effortful;
    without one — no wearable, no consent, stale reading, feature off — the behaviour is exactly
    the household default. ``None`` when nothing qualifies (the caller answers 404)."""
    moment = now or datetime.now(UTC)
    _, slots, _ = await get_week(session, household_id=household_id, week_start=week_start)
    exclude_ids = frozenset(s.recipe_id for s in slots if s.recipe_id is not None)
    recipes = await recipes_api.list_recipes(session)
    by_id = {r.id: r for r in recipes}
    candidates = [
        Candidate(
            id=r.id,
            last_cooked_at=r.last_cooked_at,
            total_minutes=_total_minutes(r.prep_minutes, r.cook_minutes),
        )
        for r in recipes
    ]

    signal = await wearables_api.recovery_signal(session, member_id=member_id, today=moment.date())
    low_recovery = signal.available and signal.low_recovery
    pick = (
        pick_quickest(candidates, now=moment, lockout_days=lockout_days, exclude_ids=exclude_ids)
        if low_recovery
        else pick_least_recently_cooked(
            candidates, now=moment, lockout_days=lockout_days, exclude_ids=exclude_ids
        )
    )
    if pick is None or pick not in by_id:
        return None
    recipe = by_id[pick]
    reasons = ["low_recovery", "quick"] if low_recovery else ["least_recently_cooked"]
    return PersonalSuggestion(
        recipe_id=recipe.id,
        title=recipe.title,
        total_minutes=_total_minutes(recipe.prep_minutes, recipe.cook_minutes),
        reasons=reasons,
    )


def _total_minutes(prep: int | None, cook: int | None) -> int | None:
    """Prep + cook, or ``None`` when the recipe states neither — an unknown effort must stay
    unknown rather than collapse to zero (which would sort it first for a tired cook)."""
    if prep is None and cook is None:
        return None
    return (prep or 0) + (cook or 0)


async def suggest_week(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    week_start: date,
    slot_key: str,
    lockout_days: int,
    target_kcal: float | None = None,
    exclude_tags: frozenset[str] = frozenset(),
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """Fill **every empty** cell of one meal (e.g. dinner) across the week with distinct recipes.

    Two strategies (best-effort, only empty days, never repeats a recipe planned this week): without
    ``target_kcal`` it's least-recently-cooked (ADR-0052); with ``target_kcal`` it picks the recipes
    whose per-portion kcal is closest to the goal (P6-S12, ADR-0057) — macros via
    ``recipes.api.recipe_macros``. ``exclude_tags`` drops recipes carrying an excluded tag
    (allergens/diet, P6-S13, ADR-0058) before either strategy. Returns the refreshed week (an empty
    pool fills nothing, no 422). Each pick goes through ``set_slot`` (one path)."""
    _, slots, _ = await get_week(session, household_id=household_id, week_start=week_start)
    filled_days = {s.day_of_week for s in slots if s.slot == slot_key}
    empty_days = [d for d in range(7) if d not in filled_days]
    if not empty_days:
        return await get_week(session, household_id=household_id, week_start=week_start)

    exclude_ids = frozenset(s.recipe_id for s in slots if s.recipe_id is not None)
    recipes = [
        r
        for r in await recipes_api.list_recipes(session)
        if not has_excluded_tag(r.tags, exclude_tags)
    ]
    if target_kcal is not None:
        kcal_candidates: list[tuple[uuid.UUID, float]] = []
        for r in recipes:
            macros = await recipes_api.recipe_macros(session, recipe_id=r.id)
            if macros is not None:
                kcal_candidates.append((r.id, macros.kcal))
        picks = pick_for_target(
            kcal_candidates,
            target_kcal=target_kcal,
            count=len(empty_days),
            exclude_ids=exclude_ids,
        )
    else:
        candidates = [Candidate(id=r.id, last_cooked_at=r.last_cooked_at) for r in recipes]
        picks = suggest_many(
            candidates,
            count=len(empty_days),
            now=datetime.now(UTC),
            lockout_days=lockout_days,
            exclude_ids=exclude_ids,
        )
    for day, recipe_id in zip(empty_days, picks, strict=False):
        data = SlotSet(day_of_week=day, slot=slot_key, recipe_id=recipe_id)
        await set_slot(session, household_id=household_id, week_start=week_start, data=data)
    return await get_week(session, household_id=household_id, week_start=week_start)


async def copy_week(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    source_week: date,
    target_week: date,
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """Copy a week's plan into another week's **empty** cells (KONZEPT §5.4 — „Woche übernehmen").

    Best-effort and **non-destructive**: only (day, slot) cells empty in ``target_week`` are filled
    from ``source_week``; existing target entries stay untouched. Recipe **or** free text plus
    cook/note are carried over verbatim. No-op (returns the unchanged week) when source equals the
    target or the source is empty. Each copy goes through ``set_slot`` (one write path)."""
    if source_week == target_week:
        return await get_week(session, household_id=household_id, week_start=target_week)
    _, source_slots, _ = await get_week(session, household_id=household_id, week_start=source_week)
    _, target_slots, _ = await get_week(session, household_id=household_id, week_start=target_week)
    occupied = {(s.day_of_week, s.slot) for s in target_slots}
    for s in source_slots:
        if (s.day_of_week, s.slot) in occupied:
            continue
        data = SlotSet(
            day_of_week=s.day_of_week,
            slot=s.slot,
            recipe_id=s.recipe_id,
            free_text=s.free_text,
            cook_id=s.cook_id,
            note=s.note,
        )
        await set_slot(session, household_id=household_id, week_start=target_week, data=data)
    return await get_week(session, household_id=household_id, week_start=target_week)


async def clear_slot(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    week_start: date,
    day_of_week: int,
    slot_key: str,
) -> tuple[MealPlan, list[MealSlot], dict[uuid.UUID, str]]:
    """Soft-delete one slot. No-op if it is already empty. Emits ``mealplan.updated``."""
    plan = await _get_or_create_plan(session, household_id=household_id, week_start=week_start)
    slot = await session.scalar(
        select(MealSlot).where(
            MealSlot.plan_id == plan.id,
            MealSlot.day_of_week == day_of_week,
            MealSlot.slot == slot_key,
            MealSlot.deleted_at.is_(None),
        )
    )
    if slot is not None:
        slot.deleted_at = datetime.now(UTC)
        await emit(session, type="mealplan.updated", household_id=household_id, payload={})
    return await get_week(session, household_id=household_id, week_start=week_start)


async def mark_slot_cooked(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    week_start: date,
    day_of_week: int,
    slot_key: str,
) -> None:
    """Record that the recipe in a slot was cooked (KONZEPT §5.4) — bumps the recipe's history via
    ``recipes.api`` (one-way) and emits ``mealplan.cooked``. 422 if the slot is empty or free text
    (no recipe to attribute)."""
    plan = await _get_or_create_plan(session, household_id=household_id, week_start=week_start)
    slot = await session.scalar(
        select(MealSlot).where(
            MealSlot.plan_id == plan.id,
            MealSlot.day_of_week == day_of_week,
            MealSlot.slot == slot_key,
            MealSlot.deleted_at.is_(None),
        )
    )
    if slot is None or slot.recipe_id is None:
        raise ProblemException(slug="no_recipe", title="Kein Rezept in diesem Slot", status=422)
    await recipes_api.mark_cooked(
        session, household_id=household_id, recipe_id=slot.recipe_id, when=datetime.now(UTC)
    )
    await emit(session, type="mealplan.cooked", household_id=household_id, payload={})


async def create_cook_task(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    week_start: date,
    day_of_week: int,
    slot_key: str,
) -> tuple[str, uuid.UUID]:
    """Turn a planned slot into a personal cooking task „Kochen: <Gericht>" (S-03, ADR-0053).

    Assigned to the slot's ``cook_id`` or — if none — the triggering user. The dish title is the
    recipe title (via ``recipes.api``) or the free text. 422 if the slot is empty (nothing to cook).
    Created via ``tasks.api.create_personal_task`` (points 0); returns ``(title, assigned_to)``."""
    _, slots, titles = await get_week(session, household_id=household_id, week_start=week_start)
    slot = next((s for s in slots if s.day_of_week == day_of_week and s.slot == slot_key), None)
    dish = None
    if slot is not None:
        if slot.recipe_id is not None:
            dish = titles.get(slot.recipe_id)
        dish = dish or slot.free_text
    if slot is None or not dish:
        raise ProblemException(slug="no_dish", title="Kein Gericht in diesem Slot", status=422)

    assigned_to = slot.cook_id or user_id
    title = f"Kochen: {dish}"
    await tasks_api.create_personal_task(
        session, household_id=household_id, title=title, assigned_to=assigned_to
    )
    return title, assigned_to


async def create_prep_task(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    week_start: date,
    day_of_week: int,
    slot_key: str,
) -> tuple[str, uuid.UUID, str]:
    """Create an advance-prep task „Vorbereiten: <Gericht> (<Hinweis>)" if the slot's recipe needs
    lead time (Synergie S-02, ADR-0055). The recipe's steps/tags are scanned with the pure
    ``needs_prep`` detector; 422 if the slot has no recipe or nothing needs preparing ahead.
    Assigned to the slot's ``cook_id`` or the caller. Returns ``(title, assigned_to, hint)``."""
    _, slots, titles = await get_week(session, household_id=household_id, week_start=week_start)
    slot = next((s for s in slots if s.day_of_week == day_of_week and s.slot == slot_key), None)
    if slot is None or slot.recipe_id is None:
        raise ProblemException(slug="no_recipe", title="Kein Rezept in diesem Slot", status=422)
    recipe = await recipes_api.get_recipe(session, recipe_id=slot.recipe_id)
    hint = needs_prep(recipe.steps_md, recipe.tags)
    if hint is None:
        raise ProblemException(
            slug="no_prep", title="Keine Vorbereitung am Vortag nötig", status=422
        )

    assigned_to = slot.cook_id or user_id
    title = f"Vorbereiten: {titles.get(slot.recipe_id, recipe.title)} ({hint})"
    await tasks_api.create_personal_task(
        session, household_id=household_id, title=title, assigned_to=assigned_to
    )
    return title, assigned_to, hint


async def week_nutrition(
    session: AsyncSession, *, household_id: uuid.UUID, week_start: date
) -> MacroSum:
    """Sum the per-portion macros of every recipe planned in ``week_start``'s week (P6-S10).

    Each recipe-slot contributes one portion; free-text slots are ignored. Macros come from
    ``recipes.api.recipe_macros`` (which itself uses ``nutrition.api``) — the mealplanner never
    reads recipe/nutrition tables. A deleted recipe is skipped. Aggregated via ``sum_macros``."""
    _, slots, _ = await get_week(session, household_id=household_id, week_start=week_start)
    rows: list[tuple[float, float, float, float, str]] = []
    for slot in slots:
        if slot.recipe_id is None:
            continue
        macros = await recipes_api.recipe_macros(session, recipe_id=slot.recipe_id)
        if macros is not None:
            rows.append(
                (macros.kcal, macros.protein_g, macros.fat_g, macros.carbs_g, macros.confidence)
            )
    return sum_macros(rows)


async def generate_shopping(
    session: AsyncSession, *, household_id: uuid.UUID, user_id: uuid.UUID, week_start: date
) -> int:
    """Add the week's recipe ingredients to the default shopping list and return how many distinct
    items were written (KONZEPT §5.5). Ingredient lines are deduped by their text (case-insensitive)
    across the week's recipes; quantity-aware merging (unit conversion via the nutrition pipeline)
    is a later slice — it needs canonical ingredients (recipes.ingredient_id is NULL until then).

    Writes go through the shopping **sync-batch** (shopping.api), never a second write path; the
    item ids are derived deterministically from (week, label) so re-running is idempotent."""
    _, slots, _ = await get_week(session, household_id=household_id, week_start=week_start)
    recipe_ids = {s.recipe_id for s in slots if s.recipe_id is not None}
    if not recipe_ids:
        return 0

    # Dedupe ingredient lines by normalised text; keep the first occurrence's qty/unit.
    by_label: dict[str, tuple[str, str | None, str | None]] = {}
    for recipe_id in recipe_ids:
        for ing in await recipes_api.get_ingredients(session, recipe_id=recipe_id):
            key = ing.raw_text.strip().lower()
            if key and key not in by_label:
                by_label[key] = (ing.raw_text.strip(), ing.qty, ing.unit)
    if not by_label:
        return 0

    list_id = await shopping_api.ensure_default_list(
        session, household_id=household_id, user_id=user_id
    )
    ops: list[SyncOp] = []
    for key, (label, qty, unit) in by_label.items():
        fields: dict[str, object] = {"list_id": str(list_id), "label": label, "source": "mealplan"}
        if qty is not None:
            fields["qty"] = qty
        if unit is not None:
            fields["unit"] = unit
        ops.append(
            SyncOp(
                client_op_id=uuid.uuid5(_SHOP_NS, f"op:{week_start}:{key}"),
                entity="shopping_item",
                id=uuid.uuid5(_SHOP_NS, f"item:{week_start}:{key}"),
                op="upsert",
                fields=fields,
            )
        )
    await shopping_api.apply_shopping_batch(
        session, household_id=household_id, user_id=user_id, ops=ops
    )
    return len(ops)
