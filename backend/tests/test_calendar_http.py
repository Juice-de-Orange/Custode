"""End-to-end HTTP tests for the calendar (Testcontainers PG 18 + Redis): event CRUD with
If-Match, the household/personal layer visibility (ADR-0040), and owner-only edits. Skipped without
Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"
_T0 = "2026-07-01T09:00:00+00:00"
_T1 = "2026-07-01T10:00:00+00:00"


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
    return (await member.get("/v1/auth/me")).json()["user_id"]


async def _create_event(client: AsyncClient, **fields: object) -> dict[str, object]:
    body = {"title": "Termin", "starts_at": _T0, "ends_at": _T1, **fields}
    resp = await client.post("/v1/calendar/events", json=body, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_event_crud_lifecycle_with_if_match(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Zahnarzt")
        event_id = created["id"]

        got = await admin.get(f"/v1/calendar/events/{event_id}")
        assert got.status_code == 200
        etag = got.headers["etag"]

        # PATCH without If-Match -> 428; stale -> 412; correct -> 200.
        no_match = await admin.patch(
            f"/v1/calendar/events/{event_id}", json={"title": "X"}, headers=_csrf(admin)
        )
        assert no_match.status_code == 428
        stale = await admin.patch(
            f"/v1/calendar/events/{event_id}",
            json={"title": "X"},
            headers={**_csrf(admin), "If-Match": '"999"'},
        )
        assert stale.status_code == 412
        patched = await admin.patch(
            f"/v1/calendar/events/{event_id}",
            json={"title": "Zahnarzt verschoben", "busy": False},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["title"] == "Zahnarzt verschoben"
        assert patched.json()["busy"] is False

        # Delete -> gone.
        deleted = await admin.delete(f"/v1/calendar/events/{event_id}", headers=_csrf(admin))
        assert deleted.status_code == 204
        assert (await admin.get(f"/v1/calendar/events/{event_id}")).status_code == 404


async def test_household_layer_is_shared_personal_is_private(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)

        shared = await _create_event(admin, title="Hausputz", layer="household")
        private = await _create_event(admin, title="Therapie", layer="personal")

        member_list = await member.get("/v1/calendar/events")
        titles = [e["title"] for e in member_list.json()]
        assert "Hausputz" in titles
        assert "Therapie" not in titles  # personal event hidden from co-member

        # The co-member cannot fetch the foreign personal event directly either.
        assert (await member.get(f"/v1/calendar/events/{private['id']}")).status_code == 404
        # ...but can see the shared one.
        assert (await member.get(f"/v1/calendar/events/{shared['id']}")).status_code == 200


async def test_non_owner_cannot_edit(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        shared = await _create_event(admin, title="Hausputz", layer="household")
        etag = (await member.get(f"/v1/calendar/events/{shared['id']}")).headers["etag"]
        forbidden = await member.patch(
            f"/v1/calendar/events/{shared['id']}",
            json={"title": "hijack"},
            headers={**_csrf(member), "If-Match": etag},
        )
        assert forbidden.status_code == 403
        del_forbidden = await member.delete(
            f"/v1/calendar/events/{shared['id']}", headers=_csrf(member)
        )
        assert del_forbidden.status_code == 403


async def test_range_filter(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await _create_event(admin, title="Juli", starts_at=_T0, ends_at=_T1)
        await _create_event(
            admin,
            title="August",
            starts_at="2026-08-01T09:00:00+00:00",
            ends_at="2026-08-01T10:00:00+00:00",
        )
        # Pass via params= so httpx encodes the "+" (a raw "+" in the URL becomes a space -> 422).
        july = await admin.get(
            "/v1/calendar/events",
            params={"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-31T23:59:59+00:00"},
        )
        assert [e["title"] for e in july.json()] == ["Juli"]


async def test_end_before_start_is_rejected(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(
            "/v1/calendar/events",
            json={"title": "Falsch", "starts_at": _T1, "ends_at": _T0},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_recurring_event_expands_into_occurrences(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        assert created["recurring"] is True
        assert created["series_id"] == created["id"]

        # A 3-week window yields 3 weekly occurrences, all sharing the series id.
        listed = await admin.get(
            "/v1/calendar/events",
            params={"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-21T23:59:59+00:00"},
        )
        occ = [e for e in listed.json() if e["series_id"] == created["id"]]
        assert len(occ) == 3
        assert [e["starts_at"][:10] for e in occ] == ["2026-07-01", "2026-07-08", "2026-07-15"]
        assert all(e["recurring"] for e in occ)


async def test_invalid_rrule_is_rejected(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(
            "/v1/calendar/events",
            json={"title": "Kaputt", "starts_at": _T0, "ends_at": _T1, "rrule": "FREQ=NONSENSE"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_ics_feed_create_fetch_revoke(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await _create_event(admin, title="Zahnarzt")

        feed = await admin.post("/v1/calendar/feed", headers=_csrf(admin))
        assert feed.status_code == 200, feed.text
        url = feed.json()["url"]
        token = url.rsplit("/feed/", 1)[1].removesuffix(".ics")

        # The feed is fetchable WITHOUT auth (a fresh client, no cookies) and is iCalendar.
        async with _client(app) as anon:
            ics = await anon.get(f"/v1/calendar/feed/{token}.ics")
            assert ics.status_code == 200, ics.text
            assert ics.headers["content-type"].startswith("text/calendar")
            assert "BEGIN:VCALENDAR" in ics.text
            assert "SUMMARY:Zahnarzt" in ics.text

            # Revoking the feed makes the URL 404.
            assert (
                await admin.delete("/v1/calendar/feed", headers=_csrf(admin))
            ).status_code == 204
            assert (await anon.get(f"/v1/calendar/feed/{token}.ics")).status_code == 404


async def test_ics_feed_unknown_token_404(app: FastAPI) -> None:
    async with _client(app) as anon:
        resp = await anon.get("/v1/calendar/feed/nonexistent-token.ics")
        assert resp.status_code == 404


async def test_cancel_occurrence_drops_one_instance(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        window = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-21T23:59:59+00:00"}

        before = await admin.get("/v1/calendar/events", params=window)
        assert [e["starts_at"][:10] for e in before.json()] == [
            "2026-07-01",
            "2026-07-08",
            "2026-07-15",
        ]

        # Cancel the middle occurrence (no If-Match needed — set semantics, ADR-0043).
        cancelled = await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        assert cancelled.status_code == 200, cancelled.text
        assert any("2026-07-08" in d for d in cancelled.json()["exdates"])

        after = await admin.get("/v1/calendar/events", params=window)
        assert [e["starts_at"][:10] for e in after.json()] == ["2026-07-01", "2026-07-15"]

        # Idempotent: cancelling again is a no-op, the instance stays gone.
        again = await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        assert again.status_code == 200
        still = await admin.get("/v1/calendar/events", params=window)
        assert [e["starts_at"][:10] for e in still.json()] == ["2026-07-01", "2026-07-15"]


async def test_restore_occurrence_brings_it_back(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        window = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-21T23:59:59+00:00"}
        await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        restored = await admin.post(
            f"/v1/calendar/events/{created['id']}/restore-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["exdates"] == []
        back = await admin.get("/v1/calendar/events", params=window)
        assert [e["starts_at"][:10] for e in back.json()] == [
            "2026-07-01",
            "2026-07-08",
            "2026-07-15",
        ]


async def test_cancel_occurrence_on_non_series_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Einmal")  # no rrule
        resp = await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": _T0},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_cancel_non_occurrence_date_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        # 2026-07-09 is a Thursday — not on the weekly (Wednesday) cadence.
        resp = await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": "2026-07-09T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_non_owner_cannot_cancel_occurrence(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        created = await _create_event(
            admin, title="Standup", layer="household", rrule="FREQ=WEEKLY"
        )
        resp = await member.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": _T0},
            headers=_csrf(member),
        )
        assert resp.status_code == 403


async def test_ics_feed_carries_exdate(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        await admin.post(
            f"/v1/calendar/events/{created['id']}/cancel-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        feed = await admin.post("/v1/calendar/feed", headers=_csrf(admin))
        token = feed.json()["url"].rsplit("/feed/", 1)[1].removesuffix(".ics")
        async with _client(app) as anon:
            ics = await anon.get(f"/v1/calendar/feed/{token}.ics")
            assert "RRULE:FREQ=WEEKLY" in ics.text
            assert "EXDATE:20260708T090000Z" in ics.text


_ICS_SAMPLE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
    "BEGIN:VEVENT\r\nUID:import-1\r\nSUMMARY:Importiert\r\n"
    "DTSTART:20260701T090000Z\r\nDTEND:20260701T100000Z\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:import-2\r\nSUMMARY:Serie\r\n"
    "DTSTART:20260702T090000Z\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


async def test_ics_import_creates_and_dedupes(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        first = await admin.post(
            "/v1/calendar/import",
            json={"content": _ICS_SAMPLE, "layer": "household"},
            headers=_csrf(admin),
        )
        assert first.status_code == 200, first.text
        assert first.json() == {"imported": 2, "skipped": 0, "failed": 0}

        titles = [e["title"] for e in (await admin.get("/v1/calendar/events")).json()]
        assert "Importiert" in titles
        assert "Serie" in titles  # the recurring import expands into occurrences

        # Re-importing the same file is idempotent: both UIDs already exist -> skipped.
        again = await admin.post(
            "/v1/calendar/import",
            json={"content": _ICS_SAMPLE, "layer": "household"},
            headers=_csrf(admin),
        )
        assert again.json() == {"imported": 0, "skipped": 2, "failed": 0}


async def test_ics_import_counts_invalid_rrule_as_failed(app: FastAPI) -> None:
    bad = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//EN\r\n"
        "BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Kaputt\r\n"
        "DTSTART:20260701T090000Z\r\nRRULE:FREQ=NONSENSE\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post("/v1/calendar/import", json={"content": bad}, headers=_csrf(admin))
        assert resp.json() == {"imported": 0, "skipped": 0, "failed": 1}


async def test_ics_import_personal_layer_stays_private(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        await admin.post(
            "/v1/calendar/import",
            json={"content": _ICS_SAMPLE, "layer": "personal"},
            headers=_csrf(admin),
        )
        # Imported into the personal layer -> a co-member does not see them.
        member_titles = [e["title"] for e in (await member.get("/v1/calendar/events")).json()]
        assert "Importiert" not in member_titles


async def test_move_and_reset_occurrence(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        window = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-21T23:59:59+00:00"}

        # Move the 2026-07-08 09:00 occurrence to 14:00-15:00.
        moved = await admin.post(
            f"/v1/calendar/events/{created['id']}/move-occurrence",
            json={
                "occurrence_start": "2026-07-08T09:00:00+00:00",
                "new_start": "2026-07-08T14:00:00+00:00",
                "new_end": "2026-07-08T15:00:00+00:00",
            },
            headers=_csrf(admin),
        )
        assert moved.status_code == 200, moved.text

        listed = await admin.get("/v1/calendar/events", params=window)
        wk2 = next(
            e
            for e in listed.json()
            if e["series_id"] == created["id"]
            and (e["original_start"] or "").startswith("2026-07-08T09:00:00")
        )
        # The moved instance keeps its original_start key but shows the new 14:00 time.
        assert wk2["starts_at"].startswith("2026-07-08T14:00:00")
        assert wk2["ends_at"].startswith("2026-07-08T15:00:00")

        # Reset returns it to the rule time.
        reset = await admin.post(
            f"/v1/calendar/events/{created['id']}/reset-occurrence",
            json={"occurrence_start": "2026-07-08T09:00:00+00:00"},
            headers=_csrf(admin),
        )
        assert reset.status_code == 200, reset.text
        after = await admin.get("/v1/calendar/events", params=window)
        wk2b = next(
            e
            for e in after.json()
            if e["series_id"] == created["id"]
            and (e["original_start"] or "").startswith("2026-07-08T09:00:00")
        )
        assert wk2b["starts_at"].startswith("2026-07-08T09:00:00")


async def test_move_non_occurrence_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Standup", rrule="FREQ=WEEKLY")
        resp = await admin.post(
            f"/v1/calendar/events/{created['id']}/move-occurrence",
            json={
                "occurrence_start": "2026-07-09T09:00:00+00:00",  # Thursday, not on the rule
                "new_start": "2026-07-09T14:00:00+00:00",
                "new_end": "2026-07-09T15:00:00+00:00",
            },
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_non_owner_cannot_move_occurrence(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        created = await _create_event(
            admin, title="Standup", layer="household", rrule="FREQ=WEEKLY"
        )
        resp = await member.post(
            f"/v1/calendar/events/{created['id']}/move-occurrence",
            json={
                "occurrence_start": _T0,
                "new_start": "2026-07-01T14:00:00+00:00",
                "new_end": "2026-07-01T15:00:00+00:00",
            },
            headers=_csrf(member),
        )
        assert resp.status_code == 403


async def test_event_tzid_roundtrip_and_validation(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(
            admin, title="Standup", rrule="FREQ=WEEKLY", tzid="Europe/Vienna"
        )
        assert created["tzid"] == "Europe/Vienna"
        # Default is UTC when omitted.
        plain = await _create_event(admin, title="Plain")
        assert plain["tzid"] == "UTC"
        # An unknown IANA zone is rejected.
        bad = await admin.post(
            "/v1/calendar/events",
            json={"title": "X", "starts_at": _T0, "ends_at": _T1, "tzid": "Mars/Olympus"},
            headers=_csrf(admin),
        )
        assert bad.status_code == 422


async def test_event_kind_absence(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await _create_event(admin, title="Urlaub", kind="absence")
        assert created["kind"] == "absence"
        listed = await admin.get("/v1/calendar/events")
        assert any(e["kind"] == "absence" for e in listed.json())


async def test_event_kind_default_and_invalid(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        default = await _create_event(admin, title="Normal")
        assert default["kind"] == "normal"
        bad = await admin.post(
            "/v1/calendar/events",
            json={"title": "X", "starts_at": _T0, "ends_at": _T1, "kind": "bogus"},
            headers=_csrf(admin),
        )
        assert bad.status_code == 422
