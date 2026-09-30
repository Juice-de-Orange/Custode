"""Integration tests for the CalDAV write-back against a real Radicale (P9-S4, ADR-0080):
create-into-subscription, GET-modify-PUT edits that PRESERVE foreign properties (VALARM/
ATTENDEE/X-props), deletes, real 412 conflicts, remote-vanished handling, the anonymous and
keyless failure shapes, and the ext_href-heals-via-sync path. Skipped without Docker.
Fixtures mirror test_calendar_sync_radicale."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import asyncpg
import httpx
import pytest
from testcontainers.core.container import DockerContainer

import app.kernel.db.engine as engine_mod
from app.adapters.caldav.client import CaldavClient
from app.kernel.crypto import generate_key, get_secretbox
from app.kernel.http.problem import ProblemException
from app.kernel.ports.caldav import CaldavAuth, CaldavObject
from app.kernel.tenancy.session import scoped_session
from app.modules.calendar import service as calendar_service
from app.modules.calendar.creds import encode_credentials
from app.modules.calendar.schemas import EventCreate, EventUpdate
from app.modules.calendar.sync import sync_all_subscriptions
from app.settings import get_settings
from conftest import PgDatabase

_RADICALE_IMAGE = "tomsquest/docker-radicale:3.7.6.0"
_RADICALE_USER = "custode"
_RADICALE_PASS = "radicale-test-pass"  # test fixture, not a real secret
_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


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


@pytest.fixture(scope="module")
def radicale(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    cfg = tmp_path_factory.mktemp("radicale")
    (cfg / "config").write_text(
        "[server]\nhosts = 0.0.0.0:5232\n\n"
        "[auth]\ntype = htpasswd\nhtpasswd_filename = /config/users\n"
        "htpasswd_encryption = plain\n\n"
        "[rights]\ntype = owner_only\n\n"
        "[storage]\nfilesystem_folder = /data/collections\n"
    )
    (cfg / "users").write_text(f"{_RADICALE_USER}:{_RADICALE_PASS}\n")
    # pytest tmp dirs are 0700 — the container's radicale user could not read the bind mount.
    cfg.chmod(0o755)
    (cfg / "config").chmod(0o644)
    (cfg / "users").chmod(0o644)
    try:
        container = (
            DockerContainer(_RADICALE_IMAGE)
            .with_exposed_ports(5232)
            .with_env("TAKE_FILE_OWNERSHIP", "true")
            .with_volume_mapping(str(cfg), "/config", "ro")
        )
        container.start()
    except Exception as exc:  # Docker not available locally
        pytest.skip(f"Docker/Radicale not available: {exc}")
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5232))
        base = f"http://{host}:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                httpx.get(base + "/", timeout=2)
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    pytest.skip("Radicale container did not become ready")
                time.sleep(0.5)
        yield base
    finally:
        container.stop()


@pytest.fixture(autouse=True)
def caldav_env(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CUSTODE_CALDAV_ALLOW_PRIVATE_URLS", "1")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CUSTODE_CALDAV_ALLOW_PRIVATE_URLS", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def crypto_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CUSTODE_CRYPTO_KEY", generate_key())
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()


# --- helpers ------------------------------------------------------------------

_AUTH = (_RADICALE_USER, _RADICALE_PASS)


def _collection(radicale_base: str, name: str) -> str:
    url = f"{radicale_base}/{_RADICALE_USER}/{name}/"
    resp = httpx.request("MKCALENDAR", url, auth=_AUTH, timeout=10)
    assert resp.status_code in (201, 405), resp.text
    return url


def _put_raw(collection_url: str, uid: str, ics: str) -> None:
    resp = httpx.put(
        f"{collection_url}{uid}.ics",
        content=ics,
        headers={"Content-Type": "text/calendar"},
        auth=_AUTH,
        timeout=10,
    )
    assert resp.status_code in (201, 204), (resp.status_code, resp.text)


def _get_remote(collection_url: str, uid: str) -> httpx.Response:
    return httpx.get(f"{collection_url}{uid}.ics", auth=_AUTH, timeout=10)


def _delete_remote(collection_url: str, uid: str) -> None:
    resp = httpx.delete(f"{collection_url}{uid}.ics", auth=_AUTH, timeout=10)
    assert resp.status_code in (200, 204), resp.status_code


async def _insert_subscription(
    pg: PgDatabase,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    url: str,
    creds_enc: str | None,
) -> uuid.UUID:
    sub_id = uuid.uuid4()
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute(
            "INSERT INTO external_calendar_subscriptions "
            "(id, household_id, member_id, label, caldav_url, creds_enc) "
            "VALUES ($1,$2,$3,'Test',$4,$5);",
            sub_id,
            household_id,
            member_id,
            url,
            creds_enc,
        )
    finally:
        await conn.close()
    return sub_id


async def _fetch(pg: PgDatabase, query: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        return list(await conn.fetch(query, *args))
    finally:
        await conn.close()


def _encoded_creds(password: str = _RADICALE_PASS) -> str:
    box = get_secretbox()
    assert box is not None
    return encode_credentials(box, username=_RADICALE_USER, password=_RADICALE_PASS)


def _client() -> CaldavClient:
    return CaldavClient(get_settings())


async def _run_sync() -> object:
    return await sync_all_subscriptions(caldav=_client(), now=datetime.now(UTC))


def _create_payload(**overrides: object) -> EventCreate:
    kwargs: dict = {"title": "Neuer Termin", "starts_at": _T0, "ends_at": _T1}
    kwargs.update(overrides)
    return EventCreate(**kwargs)


_MIRROR_SQL = (
    "SELECT id, title, version, ext_href, ext_etag, deleted_at FROM calendar_events "
    "WHERE subscription_id = $1 AND source_uid = $2;"
)


# --- tests --------------------------------------------------------------------


async def test_create_lands_remotely_and_survives_sync(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-create")
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    async with scoped_session(household_id=household, user_id=member) as session:
        event = await calendar_service.create_event(
            session,
            household_id=household,
            owner_id=member,
            data=_create_payload(subscription_id=sub_id, layer="household"),  # layer forced (E5)
            caldav=_client(),
        )
        event_uid = event.source_uid
        assert event.layer == "personal"
        assert event.ext_href is not None
        assert event.subscription_id == sub_id
    assert event_uid is not None

    remote = _get_remote(col, event_uid)
    assert remote.status_code == 200
    assert "SUMMARY:Neuer Termin" in remote.text
    assert "METHOD" not in remote.text

    stats = await _run_sync()  # the mirror row matches the remote — nothing to reconcile
    assert (stats.created, stats.updated, stats.deleted) == (0, 0, 0)  # type: ignore[attr-defined]


async def test_edit_preserves_foreign_properties(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-edit")
    foreign = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Fremd//EN\r\n"
        "BEGIN:VEVENT\r\nUID:foreign-1\r\nDTSTAMP:20260701T000000Z\r\n"
        "DTSTART:20260801T090000Z\r\nDTEND:20260801T100000Z\r\n"
        "SUMMARY:Alter Titel\r\n"
        "ATTENDEE;CN=WG:mailto:wg@example.de\r\n"
        "X-CUSTOM:bleibt\r\n"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Erinnerung\r\nTRIGGER:-PT10M\r\nEND:VALARM\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    _put_raw(col, "foreign-1", foreign)
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    [row] = await _fetch(pg, _MIRROR_SQL, sub_id, "foreign-1")
    old_etag = row["ext_etag"]

    async with scoped_session(household_id=household, user_id=member) as session:
        await calendar_service.update_event(
            session,
            household_id=household,
            viewer_id=member,
            event_id=row["id"],
            expected_version=row["version"],
            data=EventUpdate(title="Neuer Titel"),
            caldav=_client(),
        )

    remote = _get_remote(col, "foreign-1")
    assert "SUMMARY:Neuer Titel" in remote.text
    for kept in ("ATTENDEE;CN=WG:mailto:wg@example.de", "X-CUSTOM:bleibt", "BEGIN:VALARM"):
        assert kept in remote.text, kept
    [row2] = await _fetch(pg, _MIRROR_SQL, sub_id, "foreign-1")
    assert row2["title"] == "Neuer Titel"
    assert row2["ext_etag"] is not None and row2["ext_etag"] != old_etag
    stats = await _run_sync()  # local and remote agree — no reconcile churn
    assert (stats.created, stats.updated, stats.deleted) == (0, 0, 0)  # type: ignore[attr-defined]


async def test_delete_removes_remotely_and_conflicts_on_stale_etag(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-delete")
    base = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n"
        "DTSTAMP:20260701T000000Z\r\nDTSTART:20260801T090000Z\r\nSUMMARY:{summary}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    _put_raw(col, "del-1", base.format(uid="del-1", summary="Weg damit"))
    _put_raw(col, "del-2", base.format(uid="del-2", summary="Konflikt"))
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    [row1] = await _fetch(pg, _MIRROR_SQL, sub_id, "del-1")
    [row2] = await _fetch(pg, _MIRROR_SQL, sub_id, "del-2")

    # Plain delete: remote resource disappears, local row tombstones.
    async with scoped_session(household_id=household, user_id=member) as session:
        await calendar_service.delete_event(
            session,
            household_id=household,
            viewer_id=member,
            event_id=row1["id"],
            caldav=_client(),
        )
    assert _get_remote(col, "del-1").status_code == 404
    [row1b] = await _fetch(pg, _MIRROR_SQL, sub_id, "del-1")
    assert row1b["deleted_at"] is not None

    # Conflict: the remote changed after our sync -> stored ETag is stale -> real 412.
    _put_raw(col, "del-2", base.format(uid="del-2", summary="Extern geändert"))
    with pytest.raises(ProblemException) as exc:
        async with scoped_session(household_id=household, user_id=member) as session:
            await calendar_service.delete_event(
                session,
                household_id=household,
                viewer_id=member,
                event_id=row2["id"],
                caldav=_client(),
            )
    assert exc.value.slug == "external_conflict"
    [row2b] = await _fetch(pg, _MIRROR_SQL, sub_id, "del-2")
    assert row2b["deleted_at"] is None  # rollback kept the mirror
    assert _get_remote(col, "del-2").status_code == 200


async def test_remote_vanished_edit_conflicts_delete_succeeds(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-gone")
    _put_raw(
        col,
        "gone-1",
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:gone-1\r\n"
        "DTSTAMP:20260701T000000Z\r\nDTSTART:20260801T090000Z\r\nSUMMARY:Da\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n",
    )
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    [row] = await _fetch(pg, _MIRROR_SQL, sub_id, "gone-1")
    _delete_remote(col, "gone-1")

    with pytest.raises(ProblemException) as exc:
        async with scoped_session(household_id=household, user_id=member) as session:
            await calendar_service.update_event(
                session,
                household_id=household,
                viewer_id=member,
                event_id=row["id"],
                expected_version=row["version"],
                data=EventUpdate(title="Egal"),
                caldav=_client(),
            )
    assert exc.value.slug == "external_conflict"

    async with scoped_session(household_id=household, user_id=member) as session:
        await calendar_service.delete_event(  # already gone remotely = success
            session,
            household_id=household,
            viewer_id=member,
            event_id=row["id"],
            caldav=_client(),
        )
    [row2] = await _fetch(pg, _MIRROR_SQL, sub_id, "gone-1")
    assert row2["deleted_at"] is not None


async def test_anonymous_write_surfaces_auth_failure(pg: PgDatabase, radicale: str) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = f"{radicale}/{_RADICALE_USER}/wb-anon/"  # Radicale demands auth -> 401 on PUT
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=None
    )
    with pytest.raises(ProblemException) as exc:
        async with scoped_session(household_id=household, user_id=member) as session:
            await calendar_service.create_event(
                session,
                household_id=household,
                owner_id=member,
                data=_create_payload(subscription_id=sub_id),
                caldav=_client(),
            )
    assert exc.value.slug == "caldav_write_failed"
    assert exc.value.extra.get("category") == "auth_failed"
    assert (
        await _fetch(pg, "SELECT id FROM calendar_events WHERE subscription_id=$1;", sub_id) == []
    )


async def test_keyless_credentialed_write_is_503(pg: PgDatabase) -> None:
    # No CUSTODE_CRYPTO_KEY: a credentialed subscription cannot decrypt -> 503 before any I/O.
    household, member = uuid.uuid4(), uuid.uuid4()
    sub_id = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59994/x/",
        creds_enc="v1:whatever",
    )
    with pytest.raises(ProblemException) as exc:
        async with scoped_session(household_id=household, user_id=member) as session:
            await calendar_service.create_event(
                session,
                household_id=household,
                owner_id=member,
                data=_create_payload(subscription_id=sub_id),
                caldav=_client(),
            )
    assert exc.value.slug == "crypto_unconfigured"


async def test_missing_ext_href_heals_via_sync(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-heal")
    _put_raw(
        col,
        "heal-1",
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:heal-1\r\n"
        "DTSTAMP:20260701T000000Z\r\nDTSTART:20260801T090000Z\r\nSUMMARY:Alt\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n",
    )
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    # Simulate a 9-S3-era row (pre-0067): anchors missing.
    await _fetch(
        pg,
        "UPDATE calendar_events SET ext_href = NULL, ext_etag = NULL "
        "WHERE subscription_id=$1 RETURNING id;",
        sub_id,
    )
    [row] = await _fetch(pg, _MIRROR_SQL, sub_id, "heal-1")
    with pytest.raises(ProblemException) as exc:
        async with scoped_session(household_id=household, user_id=member) as session:
            await calendar_service.update_event(
                session,
                household_id=household,
                viewer_id=member,
                event_id=row["id"],
                expected_version=row["version"],
                data=EventUpdate(title="Neu"),
                caldav=_client(),
            )
    assert exc.value.slug == "external_not_synced"

    await _run_sync()  # restamps ext_href/ext_etag
    [row2] = await _fetch(pg, _MIRROR_SQL, sub_id, "heal-1")
    assert row2["ext_href"] is not None
    async with scoped_session(household_id=household, user_id=member) as session:
        await calendar_service.update_event(
            session,
            household_id=household,
            viewer_id=member,
            event_id=row2["id"],
            expected_version=row2["version"],
            data=EventUpdate(title="Neu"),
            caldav=_client(),
        )
    assert "SUMMARY:Neu" in _get_remote(col, "heal-1").text


async def test_time_edit_and_rrule_clear_round_trip(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "wb-time")
    _put_raw(
        col,
        "serie-1",
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:serie-1\r\n"
        "DTSTAMP:20260701T000000Z\r\nDTSTART:20260801T090000Z\r\nDTEND:20260801T100000Z\r\n"
        "SUMMARY:Serie\r\nRRULE:FREQ=WEEKLY\r\nEXDATE:20260808T090000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n",
    )
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    [row] = await _fetch(pg, _MIRROR_SQL, sub_id, "serie-1")

    new_start = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)
    new_end = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
    async with scoped_session(household_id=household, user_id=member) as session:
        await calendar_service.update_event(
            session,
            household_id=household,
            viewer_id=member,
            event_id=row["id"],
            expected_version=row["version"],
            data=EventUpdate(starts_at=new_start, ends_at=new_end, rrule=""),  # "" clears
            caldav=_client(),
        )
    remote = _get_remote(col, "serie-1").text
    assert "DTSTART:20260801T140000Z" in remote
    assert "DTEND:20260801T150000Z" in remote
    assert "RRULE" not in remote and "EXDATE" not in remote
    stats = await _run_sync()  # remote and local agree — the sync must not fight back
    assert (stats.created, stats.updated, stats.deleted) == (0, 0, 0)  # type: ignore[attr-defined]
    [row2] = await _fetch(
        pg,
        "SELECT starts_at, rrule, exdates FROM calendar_events WHERE id=$1;",
        row["id"],
    )
    assert row2["starts_at"] == new_start
    assert row2["rrule"] is None and list(row2["exdates"]) == []


class _EtagOnlyCaldav:
    """Same content, rotating ETag — the sync must restamp WITHOUT counting an update."""

    def __init__(self) -> None:
        self.etag = '"r1"'

    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]:
        ics = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:stable-1\r\nSUMMARY:Stabil\r\n"
            "DTSTART:20260801T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        return [CaldavObject(href="/x/stable-1.ics", etag=self.etag, ics_text=ics)]


async def test_sync_restamps_etag_without_counting_updates(pg: PgDatabase) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url="http://127.0.0.1:1/x/", creds_enc=None
    )
    fake = _EtagOnlyCaldav()
    await sync_all_subscriptions(caldav=fake, now=datetime.now(UTC))
    fake.etag = '"r2"'  # server rotated the etag; content identical
    stats = await sync_all_subscriptions(caldav=fake, now=datetime.now(UTC))
    assert (stats.created, stats.updated, stats.deleted) == (0, 0, 0)
    [row] = await _fetch(
        pg,
        "SELECT ext_etag FROM calendar_events WHERE subscription_id=$1 AND source_uid='stable-1';",
        sub_id,
    )
    assert row["ext_etag"] == '"r2"'  # anchor tracked anyway (a stale one would fail If-Match)
