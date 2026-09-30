"""Integration tests for the CalDAV pull-sync against a real Radicale server (P9-S3, ADR-0079):
Testcontainers PG 18 + a pinned Radicale container (htpasswd/plain auth). Create/update/delete
round-trips, credentialed subscriptions (SecretBox), failure isolation, the keyless graceful
path, the Null-adapter fail-safe and the S-16 busy-signal proof. Skipped without Docker."""

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
from app.adapters.null import NullCaldav
from app.caldav_factory import build_caldav
from app.kernel.crypto import generate_key, get_secretbox
from app.kernel.ports.caldav import ANONYMOUS, CaldavAuth, CaldavObject
from app.kernel.tenancy.session import scoped_session
from app.modules.calendar import service as calendar_service
from app.modules.calendar.creds import encode_credentials
from app.modules.calendar.sync import SyncStats, sync_all_subscriptions
from app.settings import get_settings
from conftest import PgDatabase

_RADICALE_IMAGE = "tomsquest/docker-radicale:3.7.6.0"
_RADICALE_USER = "custode"
_RADICALE_PASS = "radicale-test-pass"  # test fixture, not a real secret


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
    """A pinned Radicale with one htpasswd/plain user. Yields the base URL from the host."""
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
        # Readiness: poll HTTP instead of grepping logs (any response means the server is up).
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
    """Loopback targets are fine in tests; the SSRF guard stays on for everything else."""
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
    assert resp.status_code in (201, 405), resp.text  # 405 = already exists (module-shared server)
    return url


def _put_event(collection_url: str, uid: str, vevent_body: str) -> None:
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Custode-Test//EN\r\n"
        f"BEGIN:VEVENT\r\nUID:{uid}\r\n{vevent_body}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    resp = httpx.put(
        f"{collection_url}{uid}.ics",
        content=ics,
        headers={"Content-Type": "text/calendar"},
        auth=_AUTH,
        timeout=10,
    )
    assert resp.status_code in (201, 204), (resp.status_code, resp.text)


def _delete_event(collection_url: str, uid: str) -> None:
    resp = httpx.delete(f"{collection_url}{uid}.ics", auth=_AUTH, timeout=10)
    assert resp.status_code in (200, 204), resp.status_code


async def _insert_subscription(
    pg: PgDatabase,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    url: str,
    creds_enc: str | None,
    enabled: bool = True,
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
            "(id, household_id, member_id, label, caldav_url, creds_enc, enabled) "
            "VALUES ($1,$2,$3,'Test',$4,$5,$6);",
            sub_id,
            household_id,
            member_id,
            url,
            creds_enc,
            enabled,
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
    assert box is not None  # crypto_key fixture required
    return encode_credentials(box, username=_RADICALE_USER, password=password)


async def _run_sync() -> SyncStats:
    return await sync_all_subscriptions(caldav=CaldavClient(get_settings()), now=datetime.now(UTC))


_EVENTS_SQL = (
    "SELECT source_uid, title, busy, tzid, layer, owner_id, all_day, deleted_at "
    "FROM calendar_events WHERE subscription_id = $1 ORDER BY source_uid;"
)


# --- tests --------------------------------------------------------------------


async def test_full_sync_roundtrip(pg: PgDatabase, radicale: str, crypto_key: None) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "work")
    _put_event(
        col, "ev-normal", "SUMMARY:Meeting\r\nDTSTART:20260801T090000Z\r\nDTEND:20260801T100000Z"
    )
    _put_event(
        col, "ev-free", "SUMMARY:Geburtstag\r\nDTSTART;VALUE=DATE:20260802\r\nTRANSP:TRANSPARENT"
    )
    _put_event(
        col,
        "ev-series",
        "SUMMARY:Standup\r\nDTSTART;TZID=Europe/Vienna:20260803T090000\r\n"
        "DTEND;TZID=Europe/Vienna:20260803T091500\r\nRRULE:FREQ=WEEKLY",
    )
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )

    stats = await _run_sync()
    assert stats.failed == 0
    assert stats.created == 3

    rows = {r["source_uid"]: r for r in await _fetch(pg, _EVENTS_SQL, sub_id)}
    assert set(rows) == {"ev-normal", "ev-free", "ev-series"}
    for row in rows.values():
        assert row["layer"] == "personal"
        assert row["owner_id"] == member
        assert row["deleted_at"] is None
    assert rows["ev-normal"]["busy"] is True
    assert rows["ev-free"]["busy"] is False  # TRANSP:TRANSPARENT
    assert rows["ev-free"]["all_day"] is True
    assert rows["ev-series"]["tzid"] == "Europe/Vienna"  # DST anchor preserved (ADR-0047)

    sub_rows = await _fetch(
        pg,
        "SELECT last_sync_at, last_sync_error FROM external_calendar_subscriptions WHERE id=$1;",
        sub_id,
    )
    assert sub_rows[0]["last_sync_at"] is not None
    assert sub_rows[0]["last_sync_error"] is None

    # Idempotency: a second run changes nothing.
    stats2 = await _run_sync()
    assert (stats2.created, stats2.updated, stats2.deleted) == (0, 0, 0)

    # Remote update -> exactly one row updated.
    _put_event(
        col,
        "ev-normal",
        "SUMMARY:Meeting (neu)\r\nDTSTART:20260801T090000Z\r\nDTEND:20260801T100000Z",
    )
    stats3 = await _run_sync()
    assert (stats3.created, stats3.updated, stats3.deleted) == (0, 1, 0)
    rows = {r["source_uid"]: r for r in await _fetch(pg, _EVENTS_SQL, sub_id)}
    assert rows["ev-normal"]["title"] == "Meeting (neu)"

    # Remote delete -> soft-deleted; the UID reappearing -> a fresh live row.
    _delete_event(col, "ev-free")
    stats4 = await _run_sync()
    assert (stats4.created, stats4.updated, stats4.deleted) == (0, 0, 1)
    rows_all = await _fetch(pg, _EVENTS_SQL, sub_id)
    free = [r for r in rows_all if r["source_uid"] == "ev-free"]
    assert len(free) == 1 and free[0]["deleted_at"] is not None

    _put_event(
        col, "ev-free", "SUMMARY:Geburtstag\r\nDTSTART;VALUE=DATE:20260802\r\nTRANSP:TRANSPARENT"
    )
    stats5 = await _run_sync()
    assert stats5.created == 1  # partial unique index allows the re-appearance
    free = [r for r in await _fetch(pg, _EVENTS_SQL, sub_id) if r["source_uid"] == "ev-free"]
    assert sorted(r["deleted_at"] is None for r in free) == [False, True]  # tombstone + live row


async def test_failure_isolation_and_error_categories(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "iso")
    _put_event(col, "iso-1", "SUMMARY:Da\r\nDTSTART:20260801T090000Z")

    good = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    bad_auth = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url=f"{radicale}/{_RADICALE_USER}/other/",
        creds_enc=_encoded_creds(password="falsch"),
    )
    unreachable = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59997/nope/",
        creds_enc=None,
    )

    stats = await _run_sync()
    # Global counters include earlier tests' subscriptions (their creds were encoded with a
    # different per-test key -> creds_undecryptable); the per-subscription assertions below are
    # the exact ones.
    assert stats.failed >= 2
    assert stats.synced >= 1

    errors = {
        r["id"]: r["last_sync_error"]
        for r in await _fetch(
            pg,
            "SELECT id, last_sync_error FROM external_calendar_subscriptions WHERE id = ANY($1);",
            [good, bad_auth, unreachable],
        )
    }
    assert errors[good] is None
    assert errors[bad_auth] == "auth_failed"
    assert errors[unreachable] == "unreachable"
    # The good subscription synced despite its broken neighbours.
    assert len(await _fetch(pg, _EVENTS_SQL, good)) == 1


class _FakeCaldav:
    """Anonymous-path stand-in (Radicale needs auth; the anonymous flow differs only by the
    missing Authorization header, covered here)."""

    def __init__(self, objects: list[CaldavObject]) -> None:
        self._objects = objects

    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]:
        assert auth == ANONYMOUS  # anonymous subscription
        return self._objects


async def test_keyless_deployment_skips_credentialed_but_syncs_anonymous(
    pg: PgDatabase,
) -> None:
    # No CUSTODE_CRYPTO_KEY set (the autouse env fixture does not set one): a credentialed
    # subscription pauses with crypto_unconfigured, an anonymous one keeps syncing (ADR-0077).
    household, member = uuid.uuid4(), uuid.uuid4()
    with_creds = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59996/x/",
        creds_enc="v1:whatever",  # never decrypted — the missing key short-circuits first
    )
    anonymous = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59996/y/",
        creds_enc=None,
    )
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:anon-1\r\nSUMMARY:Frei\r\n"
        "DTSTART:20260801T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )
    fake = _FakeCaldav([CaldavObject(href="/y/anon-1.ics", etag=None, ics_text=ics)])

    stats = await sync_all_subscriptions(caldav=fake, now=datetime.now(UTC))
    errors = {
        r["id"]: r["last_sync_error"]
        for r in await _fetch(
            pg,
            "SELECT id, last_sync_error FROM external_calendar_subscriptions WHERE id = ANY($1);",
            [with_creds, anonymous],
        )
    }
    assert errors[with_creds] == "crypto_unconfigured"
    assert errors[anonymous] is None
    assert len(await _fetch(pg, _EVENTS_SQL, anonymous)) == 1
    assert stats.failed >= 1


async def test_null_adapter_never_tombstones_mirrors(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    # Kill-switch fail-safe: even if the sync ran with the Null adapter, the mirrors survive —
    # NullCaldav raises a skip instead of answering "empty collection".
    settings = get_settings()
    assert isinstance(build_caldav(settings), CaldavClient)  # switch on -> real client
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "nulltest")
    _put_event(col, "keep-1", "SUMMARY:Bleibt\r\nDTSTART:20260801T090000Z")
    sub_id = await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()
    assert len(await _fetch(pg, _EVENTS_SQL, sub_id)) == 1

    stats = await sync_all_subscriptions(caldav=NullCaldav(), now=datetime.now(UTC))
    assert stats.deleted == 0
    rows = await _fetch(pg, _EVENTS_SQL, sub_id)
    assert len(rows) == 1 and rows[0]["deleted_at"] is None  # untouched
    errors = await _fetch(
        pg, "SELECT last_sync_error FROM external_calendar_subscriptions WHERE id=$1;", sub_id
    )
    assert errors[0]["last_sync_error"] == "sync_disabled"


async def test_disabled_and_deleted_subscriptions_are_not_enumerated(
    pg: PgDatabase,
) -> None:
    household, member = uuid.uuid4(), uuid.uuid4()
    paused = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59995/paused/",
        creds_enc=None,
        enabled=False,
    )
    tombstoned = await _insert_subscription(
        pg,
        household_id=household,
        member_id=member,
        url="http://127.0.0.1:59995/gone/",
        creds_enc=None,
    )
    conn_rows = await _fetch(
        pg,
        "UPDATE external_calendar_subscriptions SET deleted_at = now() WHERE id=$1 RETURNING id;",
        tombstoned,
    )
    assert conn_rows
    # An unreachable URL would record an error — being skipped entirely proves the filter
    # (BUGLOG 2026-07-08 checklist: maint enumeration filters deleted_at AND enabled).
    await sync_all_subscriptions(caldav=CaldavClient(get_settings()), now=datetime.now(UTC))
    rows = {
        r["id"]: r["last_sync_error"]
        for r in await _fetch(
            pg,
            "SELECT id, last_sync_error FROM external_calendar_subscriptions WHERE id = ANY($1);",
            [paused, tombstoned],
        )
    }
    assert rows[paused] is None
    assert rows[tombstoned] is None


async def test_mirrored_busy_event_feeds_scheduling_signal(
    pg: PgDatabase, radicale: str, crypto_key: None
) -> None:
    # S-16 proof: the mirrored busy event blocks the subscriber's slots; TRANSP does not.
    household, member = uuid.uuid4(), uuid.uuid4()
    col = _collection(radicale, "busy")
    _put_event(
        col, "block-1", "SUMMARY:Termin\r\nDTSTART:20260810T090000Z\r\nDTEND:20260810T100000Z"
    )
    _put_event(
        col,
        "free-1",
        "SUMMARY:Frei\r\nDTSTART:20260810T110000Z\r\nDTEND:20260810T120000Z\r\nTRANSP:TRANSPARENT",
    )
    await _insert_subscription(
        pg, household_id=household, member_id=member, url=col, creds_enc=_encoded_creds()
    )
    await _run_sync()

    async with scoped_session(household_id=household, user_id=member) as session:
        intervals = await calendar_service.list_busy_intervals(
            session,
            viewer_id=member,
            frm=datetime(2026, 8, 10, tzinfo=UTC),
            to=datetime(2026, 8, 11, tzinfo=UTC),
        )
    assert (
        datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    ) in intervals
    assert all(start != datetime(2026, 8, 10, 11, 0, tzinfo=UTC) for start, _ in intervals)
