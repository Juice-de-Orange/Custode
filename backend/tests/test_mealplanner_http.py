"""End-to-end HTTP tests for the mealplanner (Testcontainers PG 18 + Redis): week CRUD, recipe-title
resolution via recipes.api, free text, clear, and Monday normalisation. Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"
_WEEK = "2026-06-22"  # a Monday
_MIDWEEK = "2026-06-24"  # Wednesday of the same week -> same plan


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = {k: os.environ.get(k) for k in ("CUSTODE_DATABASE_URL", "CUSTODE_DATABASE_URL_MAINT")}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    try:
        yield
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture
def app(db: None, redis_db: None) -> FastAPI:
    return create_app()


def _client(app_obj: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_obj), base_url="http://test")


@pytest.fixture(autouse=True)
def pwned_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _zero(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _zero)


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(_CSRF)
    return {"X-CSRF-Token": token} if token else {}


async def _admin_household(client: AsyncClient) -> str:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return (await client.get("/v1/auth/me")).json()["user_id"]


async def _join_member(admin: AsyncClient, member: AsyncClient) -> str:
    invite = await admin.post(
        "/v1/household/invites", json={"role": "member"}, headers=_csrf(admin)
    )
    code = invite.json()["code"]
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await member.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Mit"},
    )
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    return str((await member.get("/v1/auth/me")).json()["user_id"])


async def _create_recipe(
    client: AsyncClient, title: str, ingredients: list[dict[str, object]] | None = None
) -> str:
    body: dict[str, object] = {"title": title}
    if ingredients is not None:
        body["ingredients"] = ingredients
    resp = await client.post("/v1/recipes", json=body, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_absence(client: AsyncClient, *, starts_at: str, ends_at: str) -> None:
    resp = await client.post(
        "/v1/calendar/events",
        json={"title": "Urlaub", "starts_at": starts_at, "ends_at": ends_at, "kind": "absence"},
        headers=_csrf(client),
    )
    assert resp.status_code == 201, resp.text


def _shopping_labels(changes: list[dict[str, object]]) -> list[str]:
    return sorted(
        str(c["fields"]["label"])
        for c in changes
        if c["entity"] == "shopping_item" and c["fields"].get("source") == "mealplan"
    )


async def test_empty_week_is_created_on_demand(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.get("/v1/mealplan", params={"week_start": _WEEK})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"week_start": _WEEK, "slots": [], "absent_days": []}


async def test_set_recipe_slot_resolves_title(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Lasagne")
        resp = await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _MIDWEEK},  # Wednesday -> normalises to Monday _WEEK
            json={"day_of_week": 4, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["week_start"] == _WEEK  # Monday-normalised
        [slot] = body["slots"]
        assert slot["day_of_week"] == 4
        assert slot["recipe_id"] == recipe_id
        assert slot["recipe_title"] == "Lasagne"


async def test_free_text_and_clear(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        set_resp = await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 5, "slot": "dinner", "free_text": "auswärts"},
            headers=_csrf(admin),
        )
        [slot] = set_resp.json()["slots"]
        assert slot["free_text"] == "auswärts"
        assert slot["recipe_title"] is None

        cleared = await admin.delete(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK, "day_of_week": 5, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert cleared.json()["slots"] == []


async def test_recipe_and_free_text_together_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Suppe")
        resp = await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={
                "day_of_week": 0,
                "slot": "lunch",
                "recipe_id": recipe_id,
                "free_text": "nope",
            },
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_generate_shopping_from_week(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(
            admin,
            "Lasagne",
            ingredients=[
                {"raw_text": "Hackfleisch", "qty": "500", "unit": "g"},
                {"raw_text": "Tomaten", "qty": "2"},
            ],
        )
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )

        gen = await admin.post(
            "/v1/mealplan/to-shopping", params={"week_start": _WEEK}, headers=_csrf(admin)
        )
        assert gen.status_code == 200, gen.text
        assert gen.json() == {"added": 2}

        pull = await admin.get("/v1/sync/shopping")
        assert _shopping_labels(pull.json()["changes"]) == ["Hackfleisch", "Tomaten"]

        # Idempotent: re-running upserts the same item ids -> no duplicates in the list.
        again = await admin.post(
            "/v1/mealplan/to-shopping", params={"week_start": _WEEK}, headers=_csrf(admin)
        )
        assert again.json() == {"added": 2}
        pull2 = await admin.get("/v1/sync/shopping")
        assert _shopping_labels(pull2.json()["changes"]) == ["Hackfleisch", "Tomaten"]


async def test_mark_cooked_updates_recipe_history(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Curry")
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 1, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        # Initially never cooked.
        assert (await admin.get(f"/v1/recipes/{recipe_id}")).json()["last_cooked_at"] is None

        cooked = await admin.post(
            "/v1/mealplan/slot/cooked",
            params={"week_start": _WEEK, "day_of_week": 1, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert cooked.status_code == 204, cooked.text
        assert (await admin.get(f"/v1/recipes/{recipe_id}")).json()["last_cooked_at"] is not None


async def test_mark_cooked_on_free_text_slot_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 1, "slot": "lunch", "free_text": "auswärts"},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/cooked",
            params={"week_start": _WEEK, "day_of_week": 1, "slot": "lunch"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_generate_shopping_empty_week(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        gen = await admin.post(
            "/v1/mealplan/to-shopping", params={"week_start": _WEEK}, headers=_csrf(admin)
        )
        assert gen.json() == {"added": 0}


async def test_set_slot_overwrites_same_cell(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        for text in ("Reste", "Pizza"):
            resp = await admin.put(
                "/v1/mealplan/slot",
                params={"week_start": _WEEK},
                json={"day_of_week": 2, "slot": "lunch", "free_text": text},
                headers=_csrf(admin),
            )
        # The same (day, slot) is upserted, not duplicated.
        slots = resp.json()["slots"]
        assert len(slots) == 1
        assert slots[0]["free_text"] == "Pizza"


async def test_suggest_fills_slot_with_a_recipe(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Risotto")
        resp = await admin.post(
            "/v1/mealplan/suggest",
            params={"week_start": _MIDWEEK, "day_of_week": 3, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["week_start"] == _WEEK  # Monday-normalised
        [slot] = body["slots"]
        assert slot["recipe_id"] == recipe_id
        assert slot["recipe_title"] == "Risotto"


async def test_suggest_avoids_recipes_already_planned_this_week(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        planned = await _create_recipe(admin, "Bohnen")
        fresh = await _create_recipe(admin, "Auflauf")
        # Plan one recipe; suggest must pick the other (variety / no repeat).
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": planned},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/suggest",
            params={"week_start": _WEEK, "day_of_week": 1, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        chosen = next(s for s in resp.json()["slots"] if s["day_of_week"] == 1)
        assert chosen["recipe_id"] == fresh


async def test_suggest_week_fills_all_empty_days_distinctly(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        ids = {await _create_recipe(admin, f"Rezept {n}") for n in range(7)}
        resp = await admin.post(
            "/v1/mealplan/suggest-week",
            params={"week_start": _WEEK, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        dinners = [s for s in resp.json()["slots"] if s["slot"] == "dinner"]
        assert len(dinners) == 7  # one per day
        chosen = [s["recipe_id"] for s in dinners]
        assert set(chosen) <= ids
        assert len(set(chosen)) == 7  # distinct — no recipe repeated across the week


async def _create_recipe_with_tags(client: AsyncClient, title: str, tags: list[str]) -> str:
    resp = await client.post(
        "/v1/recipes", json={"title": title, "tags": tags}, headers=_csrf(client)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_suggest_week_excludes_tagged_recipes(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        safe = await _create_recipe_with_tags(admin, "Nudeln", ["vegetarisch"])
        await _create_recipe_with_tags(admin, "Erdnusscurry", ["nuss"])
        resp = await admin.post(
            "/v1/mealplan/suggest-week",
            params={"week_start": _WEEK, "slot": "dinner", "exclude_tag": ["Nuss"]},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        chosen = {s["recipe_id"] for s in resp.json()["slots"] if s["slot"] == "dinner"}
        assert chosen == {safe}  # only the un-tagged recipe was used; the "nuss" one is excluded


async def test_suggest_week_with_target_kcal_fills_distinctly(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        ids = {await _create_recipe(admin, f"Ziel {n}") for n in range(7)}
        resp = await admin.post(
            "/v1/mealplan/suggest-week",
            params={"week_start": _WEEK, "slot": "dinner", "target_kcal": 700},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        dinners = [s for s in resp.json()["slots"] if s["slot"] == "dinner"]
        chosen = [s["recipe_id"] for s in dinners]
        assert set(chosen) <= ids
        assert len(set(chosen)) == len(chosen) == 7  # distinct, all days filled


async def test_suggest_week_keeps_existing_entries(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        kept = await _create_recipe(admin, "Stammgericht")
        await _create_recipe(admin, "Anderes")
        # Pre-fill Monday dinner; suggest-week must not overwrite it.
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": kept},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/suggest-week",
            params={"week_start": _WEEK, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        monday = next(
            s for s in resp.json()["slots"] if s["slot"] == "dinner" and s["day_of_week"] == 0
        )
        assert monday["recipe_id"] == kept  # untouched


async def test_suggest_week_with_no_recipes_is_noop_200(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(
            "/v1/mealplan/suggest-week",
            params={"week_start": _WEEK, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["slots"] == []


async def test_week_nutrition_empty_and_after_planning(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # Empty week: zero macros, nothing counted.
        empty = await admin.get("/v1/mealplan/nutrition", params={"week_start": _WEEK})
        assert empty.status_code == 200, empty.text
        assert empty.json() == {
            "kcal": 0.0,
            "protein_g": 0.0,
            "fat_g": 0.0,
            "carbs_g": 0.0,
            "meals_counted": 0,
            "confidence": "complete",
            "target_kcal": None,
            "verdict": None,
        }
        # Plan two recipe slots + one free-text slot; only the recipes count.
        r1 = await _create_recipe(admin, "Gericht A")
        r2 = await _create_recipe(admin, "Gericht B")
        for day, rid in ((0, r1), (1, r2)):
            await admin.put(
                "/v1/mealplan/slot",
                params={"week_start": _WEEK},
                json={"day_of_week": day, "slot": "dinner", "recipe_id": rid},
                headers=_csrf(admin),
            )
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 2, "slot": "dinner", "free_text": "auswärts"},
            headers=_csrf(admin),
        )
        summary = (await admin.get("/v1/mealplan/nutrition", params={"week_start": _WEEK})).json()
        assert summary["meals_counted"] == 2  # the two recipes, free text ignored
        assert summary["kcal"] >= 0.0
        assert summary["verdict"] is None  # no target passed -> no verdict


async def test_week_nutrition_target_verdict(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # No recipes -> meals_counted 0 -> verdict stays None even with a target.
        none_yet = (
            await admin.get(
                "/v1/mealplan/nutrition", params={"week_start": _WEEK, "target_kcal": 700}
            )
        ).json()
        assert none_yet["meals_counted"] == 0
        assert none_yet["verdict"] is None
        assert none_yet["target_kcal"] == 700.0
        # A recipe with no mapped ingredients computes 0 kcal/portion -> "under" a 700 target.
        rid = await _create_recipe(admin, "Leeres Gericht")
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": rid},
            headers=_csrf(admin),
        )
        graded = (
            await admin.get(
                "/v1/mealplan/nutrition", params={"week_start": _WEEK, "target_kcal": 700}
            )
        ).json()
        assert graded["meals_counted"] == 1
        assert graded["verdict"] == "under"


async def test_empty_week_has_no_absent_days(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.get("/v1/mealplan", params={"week_start": _WEEK})
        assert resp.status_code == 200, resp.text
        assert resp.json()["absent_days"] == []


async def test_absence_marks_weekday_in_week(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # An absence on Wednesday 2026-06-24 (index 2) within week _WEEK.
        await _create_absence(
            admin,
            starts_at="2026-06-24T08:00:00+00:00",
            ends_at="2026-06-24T18:00:00+00:00",
        )
        resp = await admin.get("/v1/mealplan", params={"week_start": _WEEK})
        assert resp.status_code == 200, resp.text
        assert resp.json()["absent_days"] == [2]


async def test_cook_task_from_recipe_slot_assigns_to_caller(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Schnitzel")
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 3, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/cook-task",
            params={"week_start": _WEEK, "day_of_week": 3, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Kochen: Schnitzel"
        assert body["assigned_to"] == user_id
        # The task really exists in the tasks module, points 0, assigned to the caller.
        tasks = (await admin.get("/v1/tasks/instances")).json()
        cook = next(t for t in tasks if t["title"] == "Kochen: Schnitzel")
        assert cook["points"] == 0
        assert cook["assigned_to"] == user_id


async def test_cook_task_uses_free_text_and_cook_id(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        cook = str(uuid.uuid4())
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 1, "slot": "lunch", "free_text": "Pfannkuchen", "cook_id": cook},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/cook-task",
            params={"week_start": _WEEK, "day_of_week": 1, "slot": "lunch"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Kochen: Pfannkuchen"
        assert body["assigned_to"] == cook  # the slot's cook, not the caller


async def _create_recipe_with_steps(client: AsyncClient, title: str, steps_md: str) -> str:
    resp = await client.post(
        "/v1/recipes", json={"title": title, "steps_md": steps_md}, headers=_csrf(client)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_prep_task_created_when_recipe_needs_lead_time(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        recipe_id = await _create_recipe_with_steps(
            admin, "Rindergulasch", "Das Fleisch über Nacht marinieren, dann schmoren."
        )
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 2, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/prep-task",
            params={"week_start": _WEEK, "day_of_week": 2, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["hint"] == "marinieren"
        assert body["title"] == "Vorbereiten: Rindergulasch (marinieren)"
        assert body["assigned_to"] == user_id
        tasks = (await admin.get("/v1/tasks/instances")).json()
        assert any(t["title"] == "Vorbereiten: Rindergulasch (marinieren)" for t in tasks)


async def test_prep_task_422_when_no_lead_time(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe_with_steps(admin, "Salat", "Alles schneiden und mischen.")
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 2, "slot": "lunch", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/prep-task",
            params={"week_start": _WEEK, "day_of_week": 2, "slot": "lunch"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422, resp.text


async def test_prep_task_422_on_free_text_slot(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 3, "slot": "dinner", "free_text": "auswärts"},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/slot/prep-task",
            params={"week_start": _WEEK, "day_of_week": 3, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422, resp.text


async def test_cook_task_on_empty_slot_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(
            "/v1/mealplan/slot/cook-task",
            params={"week_start": _WEEK, "day_of_week": 6, "slot": "dinner"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422, resp.text


async def test_copy_week_fills_empty_target_from_source(app: FastAPI) -> None:
    prev = "2026-06-15"  # the Monday before _WEEK
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Gulasch")
        # Plan two cells in the previous week (a recipe + a free-text entry).
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": prev},
            json={"day_of_week": 2, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": prev},
            json={"day_of_week": 4, "slot": "lunch", "free_text": "Reste", "cook_id": None},
            headers=_csrf(admin),
        )
        # Copy into _WEEK (default source = previous week).
        resp = await admin.post(
            "/v1/mealplan/copy", params={"week_start": _WEEK}, headers=_csrf(admin)
        )
        assert resp.status_code == 200, resp.text
        slots = {(s["day_of_week"], s["slot"]): s for s in resp.json()["slots"]}
        assert slots[(2, "dinner")]["recipe_id"] == recipe_id
        assert slots[(2, "dinner")]["recipe_title"] == "Gulasch"
        assert slots[(4, "lunch")]["free_text"] == "Reste"


async def test_copy_week_does_not_overwrite_existing(app: FastAPI) -> None:
    prev = "2026-06-15"
    async with _client(app) as admin:
        await _admin_household(admin)
        source_recipe = await _create_recipe(admin, "Quelle")
        kept = await _create_recipe(admin, "Behalten")
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": prev},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": source_recipe},
            headers=_csrf(admin),
        )
        # Target already has Monday dinner set — copy must leave it alone.
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": kept},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/copy",
            params={"week_start": _WEEK, "source_week": prev},
            headers=_csrf(admin),
        )
        assert resp.status_code == 200, resp.text
        monday = next(
            s for s in resp.json()["slots"] if s["day_of_week"] == 0 and s["slot"] == "dinner"
        )
        assert monday["recipe_id"] == kept  # untouched, not replaced by the source


async def test_copy_week_empty_source_is_noop(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(
            "/v1/mealplan/copy", params={"week_start": _WEEK}, headers=_csrf(admin)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["slots"] == []


async def test_suggest_422_when_no_recipe_qualifies(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        recipe_id = await _create_recipe(admin, "Eintopf")
        # Cook it now -> within the lockout window -> no eligible recipe.
        await admin.put(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK},
            json={"day_of_week": 0, "slot": "dinner", "recipe_id": recipe_id},
            headers=_csrf(admin),
        )
        await admin.post(
            "/v1/mealplan/slot/cooked",
            params={"week_start": _WEEK, "day_of_week": 0, "slot": "dinner"},
            headers=_csrf(admin),
        )
        # Clear the slot so the only recipe is no longer "already planned", just locked out.
        await admin.delete(
            "/v1/mealplan/slot",
            params={"week_start": _WEEK, "day_of_week": 0, "slot": "dinner"},
            headers=_csrf(admin),
        )
        resp = await admin.post(
            "/v1/mealplan/suggest",
            params={"week_start": _WEEK, "day_of_week": 2, "slot": "dinner", "lockout_days": 7},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422, resp.text
        # With lockout 0 the just-cooked recipe is eligible again.
        ok = await admin.post(
            "/v1/mealplan/suggest",
            params={"week_start": _WEEK, "day_of_week": 2, "slot": "dinner", "lockout_days": 0},
            headers=_csrf(admin),
        )
        assert ok.status_code == 200, ok.text


# --- personal suggestion (P9, ADR-0081 §9) ------------------------------------


async def _seed_reading(pg: PgDatabase, *, member_id: str, readiness: int) -> None:
    """One low/high recovery reading for the member, scoped to their household."""
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        household_id = await conn.fetchval(
            "SELECT household_id FROM memberships WHERE user_id = $1;", uuid.UUID(member_id)
        )
        await conn.execute(
            "INSERT INTO wearable_daily (household_id, member_id, provider, day, readiness) "
            "VALUES ($1,$2,'oura', CURRENT_DATE, $3);",
            household_id,
            uuid.UUID(member_id),
            readiness,
        )
    finally:
        await conn.close()


async def _slow_and_quick(client: AsyncClient) -> tuple[str, str]:
    """A long recipe cooked long ago (wins least-recently-cooked) and a quick fresh one."""
    slow = await client.post(
        "/v1/recipes",
        json={"title": "Rinderrouladen", "prep_minutes": 40, "cook_minutes": 140},
        headers=_csrf(client),
    )
    quick = await client.post(
        "/v1/recipes",
        json={"title": "Pasta", "prep_minutes": 5, "cook_minutes": 10},
        headers=_csrf(client),
    )
    return slow.json()["id"], quick.json()["id"]


async def test_personal_suggestion_writes_nothing(app: FastAPI, pg: PgDatabase) -> None:
    """The whole reason this endpoint exists: a suggestion the member's own health signal may
    shape must NOT touch the shared week plan (S-14 "nur für eigene Vorschläge")."""
    async with _client(app) as client:
        await _admin_household(client)
        await _slow_and_quick(client)

        before = (await client.get("/v1/mealplan?week_start=2026-07-27")).json()
        answer = await client.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        assert answer.status_code == 200, answer.text
        after = (await client.get("/v1/mealplan?week_start=2026-07-27")).json()

        assert answer.json()["recipe_id"]
        assert before["slots"] == after["slots"]  # nothing was planned by asking


async def test_without_a_wearable_the_household_default_applies(
    app: FastAPI, pg: PgDatabase
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _slow_and_quick(client)

        answer = await client.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        assert answer.json()["reasons"] == ["least_recently_cooked"]


async def test_a_low_recovery_reading_shifts_the_suggestion_to_the_quick_recipe(
    app: FastAPI, pg: PgDatabase
) -> None:
    async with _client(app) as client:
        member_id = await _admin_household(client)
        _, quick_id = await _slow_and_quick(client)
        await _seed_reading(pg, member_id=member_id, readiness=30)

        answer = await client.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        body = answer.json()
        assert body["recipe_id"] == quick_id
        assert body["reasons"] == ["low_recovery", "quick"]
        assert body["total_minutes"] == 15


async def test_a_good_reading_leaves_the_default_alone(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as client:
        member_id = await _admin_household(client)
        await _slow_and_quick(client)
        await _seed_reading(pg, member_id=member_id, readiness=90)

        answer = await client.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        assert answer.json()["reasons"] == ["least_recently_cooked"]


async def test_a_co_members_reading_never_shapes_my_suggestion(
    app: FastAPI, pg: PgDatabase
) -> None:
    """N-2 end to end: Bob being exhausted must not change what Alice is offered — the seam is
    member-scoped and the RLS backs it."""
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        member_id = await _join_member(admin, member)
        await _slow_and_quick(admin)
        await _seed_reading(pg, member_id=member_id, readiness=20)  # the OTHER member is tired

        answer = await admin.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        assert answer.json()["reasons"] == ["least_recently_cooked"]


async def test_no_candidate_answers_404(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        answer = await client.get("/v1/mealplan/suggestion?week_start=2026-07-27&slot=dinner")
        assert answer.status_code == 404
