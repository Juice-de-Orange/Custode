"""HTTP tests for mirrored CalDAV events (P9-S3/S4, ADR-0079/0080): the ``external`` flag,
personal-layer invisibility, the unsubscribe cascade, occurrence actions staying read-only —
and the 9-S4 write-through paths (PATCH/DELETE/POST-with-subscription) exercised against a
recording fake port injected via ``app.dependency_overrides[get_caldav]`` (E14). Testcontainers
PG 18 + Redis; mirror rows are seeded directly (the real sync/Radicale round-trips live in
test_calendar_sync_radicale / test_calendar_writeback_radicale). Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.kernel.ports.caldav import CaldavAuth, CaldavError, CaldavObject, get_caldav
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"
_T0 = "2026-08-01T09:00:00+00:00"
_T1 = "2026-08-01T10:00:00+00:00"


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


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


async def _seed_mirror_event(pg: PgDatabase, subscription_id: str) -> str:
    """Insert one mirror row for the subscription (what the sync would create)."""
    conn = await _su(pg)
    try:
        row = await conn.fetchrow(
            "SELECT household_id, member_id FROM external_calendar_subscriptions WHERE id=$1;",
            uuid.UUID(subscription_id),
        )
        assert row is not None
        event_id = await conn.fetchval(
            "INSERT INTO calendar_events (household_id, owner_id, title, starts_at, ends_at, "
            "layer, subscription_id, source_uid, ext_href, ext_etag) "
            "VALUES ($1,$2,'Extern gespiegelt',$3,$4,'personal',$5,'uid-1',"
            "'/dav/uid-1.ics','\"e1\"') RETURNING id;",
            row["household_id"],
            row["member_id"],
            datetime.fromisoformat(_T0),
            datetime.fromisoformat(_T1),
            uuid.UUID(subscription_id),
        )
        return str(event_id)
    finally:
        await conn.close()


_FAKE_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-1\r\n"
    "DTSTAMP:20260701T000000Z\r\nDTSTART:20260801T090000Z\r\nDTEND:20260801T100000Z\r\n"
    "SUMMARY:Extern gespiegelt\r\nX-KEEP:ja\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


class RecordingCaldav:
    """Fake port (E14): records every call; optionally fails one op with a given category."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_put: str | None = None
        self.fail_get: str | None = None

    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]:
        self.calls.append(("list", url))
        return []

    async def get_object(self, *, url: str, href: str, auth: CaldavAuth) -> CaldavObject:
        self.calls.append(("get", href))
        if self.fail_get is not None:
            raise CaldavError(self.fail_get)
        return CaldavObject(href=href, etag='"g1"', ics_text=_FAKE_ICS)

    async def put_object(
        self,
        *,
        url: str,
        href: str,
        ics_text: str,
        etag: str | None,
        if_none_match: bool,
        auth: CaldavAuth,
    ) -> str | None:
        self.calls.append(("put", href, etag or "", "INM" if if_none_match else ""))
        if self.fail_put is not None:
            raise CaldavError(self.fail_put)
        return '"e2"'

    async def delete_object(
        self, *, url: str, href: str, etag: str | None, auth: CaldavAuth
    ) -> None:
        self.calls.append(("delete", href, etag or ""))


async def _create_subscription(client: AsyncClient) -> str:
    resp = await client.post(
        "/v1/calendar/subscriptions",
        json={"label": "Extern", "caldav_url": "https://cal.example.org/dav/"},
        headers=_csrf(client),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_mirror_flags_and_occurrence_ops_stay_read_only(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        sub_id = await _create_subscription(admin)
        event_id = await _seed_mirror_event(pg, sub_id)

        # Visible with the additive external flag; a local event carries external=false.
        local = await admin.post(
            "/v1/calendar/events",
            json={"title": "Lokal", "starts_at": _T0, "ends_at": _T1},
            headers=_csrf(admin),
        )
        assert local.status_code == 201 and local.json()["external"] is False
        listed = await admin.get(
            "/v1/calendar/events",
            params={"from": "2026-08-01T00:00:00Z", "to": "2026-08-02T00:00:00Z"},
        )
        by_title = {e["title"]: e for e in listed.json()}
        assert by_title["Extern gespiegelt"]["external"] is True
        assert by_title["Lokal"]["external"] is False

        got = await admin.get(f"/v1/calendar/events/{event_id}")
        assert got.status_code == 200 and got.json()["external"] is True

        # Occurrence actions on mirrors STAY read-only (overrides aren't mirrored, ADR-0080).
        for action in ("cancel-occurrence", "restore-occurrence", "reset-occurrence"):
            resp = await admin.post(
                f"/v1/calendar/events/{event_id}/{action}",
                json={"occurrence_start": _T0},
                headers=_csrf(admin),
            )
            assert resp.status_code == 409, (action, resp.text)
            assert resp.json()["type"].endswith("external_event_read_only")
        moved = await admin.post(
            f"/v1/calendar/events/{event_id}/move-occurrence",
            json={"occurrence_start": _T0, "new_start": _T0, "new_end": _T1},
            headers=_csrf(admin),
        )
        assert moved.status_code == 409


async def test_mirror_patch_writes_through(app: FastAPI, pg: PgDatabase) -> None:
    fake = RecordingCaldav()
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin:
            await _admin_household(admin)
            sub_id = await _create_subscription(admin)
            event_id = await _seed_mirror_event(pg, sub_id)
            etag = (await admin.get(f"/v1/calendar/events/{event_id}")).headers["etag"]

            patched = await admin.patch(
                f"/v1/calendar/events/{event_id}",
                json={"title": "Umbenannt"},
                headers={**_csrf(admin), "If-Match": etag},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["title"] == "Umbenannt"
            # GET-modify-PUT under the FRESH GET etag (E3), never the stored one:
            assert fake.calls == [
                ("get", "/dav/uid-1.ics"),
                ("put", "/dav/uid-1.ics", '"g1"', ""),
            ]
            conn = await _su(pg)
            try:
                row = await conn.fetchrow(
                    "SELECT title, ext_etag FROM calendar_events WHERE id=$1;",
                    uuid.UUID(event_id),
                )
            finally:
                await conn.close()
            assert row is not None
            assert row["title"] == "Umbenannt"
            assert row["ext_etag"] == '"e2"'  # the PUT response etag was stored
    finally:
        app.dependency_overrides.clear()


async def test_mirror_patch_conflict_rolls_back(app: FastAPI, pg: PgDatabase) -> None:
    fake = RecordingCaldav()
    fake.fail_put = "conflict"
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin:
            await _admin_household(admin)
            sub_id = await _create_subscription(admin)
            event_id = await _seed_mirror_event(pg, sub_id)
            etag = (await admin.get(f"/v1/calendar/events/{event_id}")).headers["etag"]

            patched = await admin.patch(
                f"/v1/calendar/events/{event_id}",
                json={"title": "Umbenannt"},
                headers={**_csrf(admin), "If-Match": etag},
            )
            assert patched.status_code == 409
            assert patched.json()["type"].endswith("external_conflict")
            got = await admin.get(f"/v1/calendar/events/{event_id}")
            assert got.json()["title"] == "Extern gespiegelt"  # local row untouched
    finally:
        app.dependency_overrides.clear()


async def test_mirror_patch_readonly_fields_answer_422(app: FastAPI, pg: PgDatabase) -> None:
    fake = RecordingCaldav()
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin:
            await _admin_household(admin)
            sub_id = await _create_subscription(admin)
            event_id = await _seed_mirror_event(pg, sub_id)
            etag = (await admin.get(f"/v1/calendar/events/{event_id}")).headers["etag"]

            for payload in ({"layer": "household"}, {"kind": "absence"}, {"tzid": "Europe/Wien"}):
                resp = await admin.patch(
                    f"/v1/calendar/events/{event_id}",
                    json=payload,
                    headers={**_csrf(admin), "If-Match": etag},
                )
                assert resp.status_code == 422, (payload, resp.text)
                assert resp.json()["type"].endswith("external_field_readonly")
            assert fake.calls == []  # rejected before any remote I/O
    finally:
        app.dependency_overrides.clear()


async def test_mirror_delete_writes_through(app: FastAPI, pg: PgDatabase) -> None:
    fake = RecordingCaldav()
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin:
            await _admin_household(admin)
            sub_id = await _create_subscription(admin)
            event_id = await _seed_mirror_event(pg, sub_id)

            deleted = await admin.delete(f"/v1/calendar/events/{event_id}", headers=_csrf(admin))
            assert deleted.status_code == 204
            # DELETE uses the STORED etag as If-Match anchor (E3).
            assert fake.calls == [("delete", "/dav/uid-1.ics", '"e1"')]
            assert (await admin.get(f"/v1/calendar/events/{event_id}")).status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_create_into_subscription(app: FastAPI, pg: PgDatabase) -> None:
    fake = RecordingCaldav()
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin, _client(app) as member:
            await _admin_household(admin)
            await _join_member(admin, member)
            sub_id = await _create_subscription(admin)

            created = await admin.post(
                "/v1/calendar/events",
                json={
                    "title": "Nach draußen",
                    "starts_at": _T0,
                    "ends_at": _T1,
                    "layer": "household",  # silently forced to personal (E5)
                    "subscription_id": sub_id,
                },
                headers=_csrf(admin),
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["external"] is True
            assert body["layer"] == "personal"
            assert len(fake.calls) == 1
            op, href, _etag, inm = fake.calls[0]
            assert op == "put" and inm == "INM"  # If-None-Match: * — a create never overwrites
            assert href.startswith("/dav/") and href.endswith(".ics")

            # Foreign subscription (co-member's id) -> 404, no existence leak.
            foreign = await member.post(
                "/v1/calendar/events",
                json={
                    "title": "X",
                    "starts_at": _T0,
                    "ends_at": _T1,
                    "subscription_id": sub_id,
                },
                headers=_csrf(member),
            )
            assert foreign.status_code == 404

            # Non-round-trippable fields answer 422 (E6).
            for extra, slug in (
                ({"kind": "absence"}, "external_kind_unsupported"),
                ({"tzid": "Europe/Vienna"}, "external_tzid_unsupported"),
            ):
                resp = await admin.post(
                    "/v1/calendar/events",
                    json={
                        "title": "X",
                        "starts_at": _T0,
                        "ends_at": _T1,
                        "subscription_id": sub_id,
                        **extra,
                    },
                    headers=_csrf(admin),
                )
                assert resp.status_code == 422, (extra, resp.text)
                assert resp.json()["type"].endswith(slug)
    finally:
        app.dependency_overrides.clear()


async def test_local_events_never_touch_the_port(app: FastAPI) -> None:
    fake = RecordingCaldav()
    app.dependency_overrides[get_caldav] = lambda: fake
    try:
        async with _client(app) as admin:
            await _admin_household(admin)
            created = await admin.post(
                "/v1/calendar/events",
                json={"title": "Lokal", "starts_at": _T0, "ends_at": _T1},
                headers=_csrf(admin),
            )
            assert created.status_code == 201
            event_id = created.json()["id"]
            etag = created.headers["etag"]
            patched = await admin.patch(
                f"/v1/calendar/events/{event_id}",
                json={"title": "Lokal 2"},
                headers={**_csrf(admin), "If-Match": etag},
            )
            assert patched.status_code == 200
            deleted = await admin.delete(f"/v1/calendar/events/{event_id}", headers=_csrf(admin))
            assert deleted.status_code == 204
            assert fake.calls == []  # the local path never does remote I/O
    finally:
        app.dependency_overrides.clear()


async def test_kill_switch_answers_503(
    db: None, redis_db: None, pg: PgDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the switch off the composition installs NullCaldav (raises sync_disabled) -> a mirror
    # write answers 503 caldav_disabled instead of silently diverging from the remote.
    monkeypatch.setenv("CUSTODE_CALDAV_SYNC_ENABLED", "0")
    get_settings.cache_clear()
    try:
        app_off = create_app()
        async with _client(app_off) as admin:
            await _admin_household(admin)
            sub_id = await _create_subscription(admin)
            event_id = await _seed_mirror_event(pg, sub_id)
            etag = (await admin.get(f"/v1/calendar/events/{event_id}")).headers["etag"]
            patched = await admin.patch(
                f"/v1/calendar/events/{event_id}",
                json={"title": "Egal"},
                headers={**_csrf(admin), "If-Match": etag},
            )
            assert patched.status_code == 503
            assert patched.json()["type"].endswith("caldav_disabled")
    finally:
        monkeypatch.delenv("CUSTODE_CALDAV_SYNC_ENABLED", raising=False)
        get_settings.cache_clear()


async def test_mirror_events_stay_private_to_the_subscriber(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        sub_id = await _create_subscription(admin)
        event_id = await _seed_mirror_event(pg, sub_id)

        listed = await member.get(
            "/v1/calendar/events",
            params={"from": "2026-08-01T00:00:00Z", "to": "2026-08-02T00:00:00Z"},
        )
        assert "Extern gespiegelt" not in [e["title"] for e in listed.json()]
        assert (await member.get(f"/v1/calendar/events/{event_id}")).status_code == 404


async def test_unsubscribe_tombstones_mirror_events(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        sub_id = await _create_subscription(admin)
        event_id = await _seed_mirror_event(pg, sub_id)

        gone = await admin.delete(f"/v1/calendar/subscriptions/{sub_id}", headers=_csrf(admin))
        assert gone.status_code == 204

        conn = await _su(pg)
        try:
            deleted_at = await conn.fetchval(
                "SELECT deleted_at FROM calendar_events WHERE id=$1;", uuid.UUID(event_id)
            )
        finally:
            await conn.close()
        assert deleted_at is not None
        assert (await admin.get(f"/v1/calendar/events/{event_id}")).status_code == 404
