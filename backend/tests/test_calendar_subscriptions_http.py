"""End-to-end HTTP tests for external CalDAV subscriptions (P9-S2, Testcontainers PG 18 + Redis):
CRUD with If-Match, write-only credentials (ADR-0077 — no response ever carries the secret, the
stored value is a ``v1:`` SecretBox token), both Graceful-Enhancement paths (keyless anonymous vs.
503 with credentials), owner scoping (a co-member's subscription answers 404), the duplicate-URL
409 and the save-time URL shape validation. Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.kernel.crypto import generate_key
from app.kernel.ports.caldav import CaldavAuth, CaldavError
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"
_DAV_PASSWORD = "caldav-geheimnis-123"  # the write-only credential under test
_DAV_URL = "https://cloud.example.de/remote.php/dav/calendars/max/personal/"


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


@pytest.fixture
def crypto_key(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure a server crypto key (ADR-0077) for the credential-carrying paths."""
    monkeypatch.setenv("CUSTODE_CRYPTO_KEY", generate_key())
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_ambient_crypto_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyless is the deterministic default; tests opt in via ``crypto_key``."""
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()


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


async def _stored_creds_enc(pg: PgDatabase, subscription_id: str) -> str | None:
    """Read the persisted ciphertext directly (superuser bypasses RLS) — the only way to prove
    what actually hit the disk."""
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        value: str | None = await conn.fetchval(
            "SELECT creds_enc FROM external_calendar_subscriptions WHERE id = $1;",
            uuid.UUID(subscription_id),
        )
        return value
    finally:
        await conn.close()


async def test_subscription_crud_with_write_only_credentials(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)

        created = await admin.post(
            "/v1/calendar/subscriptions",
            json={
                "label": "Nextcloud Arbeit",
                "caldav_url": _DAV_URL,
                "username": "max@example.de",
                "password": _DAV_PASSWORD,
            },
            headers=_csrf(admin),
        )
        assert created.status_code == 201, created.text
        assert created.headers["etag"] == '"1"'
        body = created.json()
        sub_id = body["id"]
        assert body["has_credentials"] is True
        assert body["last_sync_at"] is None
        # Write-only: neither the secret nor the ciphertext ever appears on the wire.
        assert _DAV_PASSWORD not in created.text
        assert "creds_enc" not in created.text

        listed = await admin.get("/v1/calendar/subscriptions")
        assert [s["label"] for s in listed.json()] == ["Nextcloud Arbeit"]
        assert _DAV_PASSWORD not in listed.text

        got = await admin.get(f"/v1/calendar/subscriptions/{sub_id}")
        assert got.status_code == 200
        assert _DAV_PASSWORD not in got.text
        etag = got.headers["etag"]

        # Persistence: exactly one SecretBox value, never the plaintext (ADR-0077).
        stored = await _stored_creds_enc(pg, sub_id)
        assert stored is not None and stored.startswith("v1:")
        assert _DAV_PASSWORD not in stored

        # Omitting the credential fields leaves them untouched.
        renamed = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"label": "Nextcloud privat", "enabled": False},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["label"] == "Nextcloud privat"
        assert renamed.json()["enabled"] is False
        assert renamed.json()["has_credentials"] is True
        assert await _stored_creds_enc(pg, sub_id) == stored

        # New credentials replace the stored value (fresh Fernet token).
        etag = renamed.headers["etag"]
        replaced = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"username": "max@example.de", "password": "neues-geheimnis"},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert replaced.status_code == 200, replaced.text
        restored = await _stored_creds_enc(pg, sub_id)
        assert restored is not None and restored.startswith("v1:") and restored != stored

        # clear_credentials drops them.
        etag = replaced.headers["etag"]
        cleared = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"clear_credentials": True},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["has_credentials"] is False
        assert await _stored_creds_enc(pg, sub_id) is None

        # Delete -> gone; the partial unique index then allows re-subscribing the same URL.
        deleted = await admin.delete(f"/v1/calendar/subscriptions/{sub_id}", headers=_csrf(admin))
        assert deleted.status_code == 204
        assert (await admin.get(f"/v1/calendar/subscriptions/{sub_id}")).status_code == 404
        assert (await admin.get("/v1/calendar/subscriptions")).json() == []
        again = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Nextcloud neu", "caldav_url": _DAV_URL},
            headers=_csrf(admin),
        )
        assert again.status_code == 201, again.text


async def test_if_match_flow(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Anonym", "caldav_url": "https://cal.example.org/dav/"},
            headers=_csrf(admin),
        )
        sub_id = created.json()["id"]

        no_match = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}", json={"label": "X"}, headers=_csrf(admin)
        )
        assert no_match.status_code == 428
        stale = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"label": "X"},
            headers={**_csrf(admin), "If-Match": '"999"'},
        )
        assert stale.status_code == 412
        ok = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"label": "X"},
            headers={**_csrf(admin), "If-Match": created.headers["etag"]},
        )
        assert ok.status_code == 200, ok.text


async def test_graceful_paths_without_crypto_key(app: FastAPI) -> None:
    # Both enhancement paths (DoD): keyless deployments keep anonymous subscriptions fully
    # working; only credential-carrying writes answer 503 (ADR-0077).
    async with _client(app) as admin:
        await _admin_household(admin)

        anonymous = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Öffentlich", "caldav_url": "https://cal.example.org/public/"},
            headers=_csrf(admin),
        )
        assert anonymous.status_code == 201, anonymous.text
        assert anonymous.json()["has_credentials"] is False

        with_creds = await admin.post(
            "/v1/calendar/subscriptions",
            json={
                "label": "Privat",
                "caldav_url": _DAV_URL,
                "username": "max@example.de",
                "password": _DAV_PASSWORD,
            },
            headers=_csrf(admin),
        )
        assert with_creds.status_code == 503
        assert with_creds.json()["type"].endswith("crypto_unconfigured")

        sub_id = anonymous.json()["id"]
        keyless_patch = await admin.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"label": "Öffentlich (umbenannt)", "clear_credentials": True},
            headers={**_csrf(admin), "If-Match": anonymous.headers["etag"]},
        )
        assert keyless_patch.status_code == 200, keyless_patch.text


async def test_duplicate_url_answers_409(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        first = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Eins", "caldav_url": _DAV_URL},
            headers=_csrf(admin),
        )
        assert first.status_code == 201
        duplicate = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Zwei", "caldav_url": _DAV_URL},
            headers=_csrf(admin),
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["type"].endswith("subscription_exists")
        other = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Drei", "caldav_url": "https://other.example.org/dav/"},
            headers=_csrf(admin),
        )
        assert other.status_code == 201


async def test_subscriptions_are_owner_only(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        created = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "Admins Abo", "caldav_url": _DAV_URL},
            headers=_csrf(admin),
        )
        sub_id = created.json()["id"]

        # The co-member sees nothing — not in the list, not by id, not via write paths.
        assert (await member.get("/v1/calendar/subscriptions")).json() == []
        assert (await member.get(f"/v1/calendar/subscriptions/{sub_id}")).status_code == 404
        foreign_patch = await member.patch(
            f"/v1/calendar/subscriptions/{sub_id}",
            json={"label": "hijack"},
            headers={**_csrf(member), "If-Match": '"1"'},
        )
        assert foreign_patch.status_code == 404
        assert (
            await member.delete(f"/v1/calendar/subscriptions/{sub_id}", headers=_csrf(member))
        ).status_code == 404


async def test_url_and_credential_validation(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)

        async def _post(body: dict[str, object]) -> int:
            resp = await admin.post(
                "/v1/calendar/subscriptions",
                json={"label": "Test", **body},
                headers=_csrf(admin),
            )
            return resp.status_code

        assert await _post({"caldav_url": "ftp://cal.example.org/dav/"}) == 422
        assert await _post({"caldav_url": "https://"}) == 422  # no host
        # Userinfo in the URL would land credentials in the plaintext column.
        assert await _post({"caldav_url": "https://max:pass@cal.example.org/dav/"}) == 422
        assert await _post({"caldav_url": "https://cal.example.org/" + "x" * 2000}) == 422
        # Basic auth needs both parts.
        assert await _post({"caldav_url": "https://cal.example.org/dav/", "username": "max"}) == 422

        created = await admin.post(
            "/v1/calendar/subscriptions",
            json={"label": "OK", "caldav_url": "https://cal.example.org/dav/"},
            headers=_csrf(admin),
        )
        # clear_credentials excludes new credentials in the same PATCH.
        conflict = await admin.patch(
            f"/v1/calendar/subscriptions/{created.json()['id']}",
            json={"clear_credentials": True, "username": "max", "password": "p"},
            headers={**_csrf(admin), "If-Match": created.headers["etag"]},
        )
        assert conflict.status_code == 422


async def test_anonymous_is_unauthorized(app: FastAPI) -> None:
    async with _client(app) as anon:
        assert (await anon.get("/v1/calendar/subscriptions")).status_code == 401


# --- connection probe (P9) ----------------------------------------------------


class _ProbeCaldav:
    """Fake port: records the credentials it was handed, answers with objects or an error."""

    def __init__(self, *, objects: int = 0, error: str | None = None) -> None:
        self.objects, self.error = objects, error
        self.seen: list[tuple[str, CaldavAuth]] = []

    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[object]:
        self.seen.append((url, auth))
        if self.error:
            raise CaldavError(self.error)
        return [object()] * self.objects


def _with_probe(app_obj: FastAPI, probe: _ProbeCaldav) -> None:
    app_obj.state.caldav = probe


async def _create_sub(client: AsyncClient, **over: object) -> str:
    body = {"label": "Nextcloud", "caldav_url": _DAV_URL, **over}
    created = await client.post("/v1/calendar/subscriptions", json=body, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_check_reports_success_with_a_count(app: FastAPI, crypto_key: None) -> None:
    probe = _ProbeCaldav(objects=3)
    _with_probe(app, probe)
    async with _client(app) as client:
        await _admin_household(client)
        sub_id = await _create_sub(client, username="max", password=_DAV_PASSWORD)

        answer = await client.post(
            f"/v1/calendar/subscriptions/{sub_id}/check", headers=_csrf(client)
        )
        assert answer.status_code == 200, answer.text
        assert answer.json() == {"ok": True, "category": None, "objects": 3}
        # The probe used the stored credentials — that is the whole point of checking.
        assert probe.seen[0][1] == CaldavAuth(username="max", password=_DAV_PASSWORD)


async def test_check_reports_a_failure_as_data_not_as_an_error(
    app: FastAPI, crypto_key: None
) -> None:
    """A typo is an expected outcome, not a server fault — so 200 with ok=false, and the same
    category slug the sync would record."""
    _with_probe(app, _ProbeCaldav(error="auth_failed"))
    async with _client(app) as client:
        await _admin_household(client)
        sub_id = await _create_sub(client, username="max", password=_DAV_PASSWORD)

        answer = await client.post(
            f"/v1/calendar/subscriptions/{sub_id}/check", headers=_csrf(client)
        )
        assert answer.status_code == 200
        assert answer.json()["ok"] is False
        assert answer.json()["category"] == "auth_failed"


async def test_check_writes_nothing(app: FastAPI, pg: PgDatabase, crypto_key: None) -> None:
    """A check is a probe, not a half-hearted sync: no mirror, no last_sync_at, not even
    last_sync_error. The next cron tick records the truth anyway."""
    _with_probe(app, _ProbeCaldav(error="unreachable"))
    async with _client(app) as client:
        await _admin_household(client)
        sub_id = await _create_sub(client)
        await client.post(f"/v1/calendar/subscriptions/{sub_id}/check", headers=_csrf(client))

        after = (await client.get(f"/v1/calendar/subscriptions/{sub_id}")).json()
        assert after["last_sync_error"] is None
        assert after["last_sync_at"] is None


async def test_check_on_a_foreign_subscription_is_404(app: FastAPI, crypto_key: None) -> None:
    _with_probe(app, _ProbeCaldav())
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        sub_id = await _create_sub(member, username="max", password=_DAV_PASSWORD)

        answer = await admin.post(
            f"/v1/calendar/subscriptions/{sub_id}/check", headers=_csrf(admin)
        )
        assert answer.status_code == 404


async def test_check_of_an_anonymous_subscription_needs_no_crypto_key(app: FastAPI) -> None:
    """Graceful Enhancement: without a server key the credential-free path still works."""
    _with_probe(app, _ProbeCaldav(objects=1))
    async with _client(app) as client:
        await _admin_household(client)
        sub_id = await _create_sub(client)

        answer = await client.post(
            f"/v1/calendar/subscriptions/{sub_id}/check", headers=_csrf(client)
        )
        assert answer.status_code == 200
        assert answer.json()["ok"] is True


async def test_check_requires_csrf(app: FastAPI, crypto_key: None) -> None:
    _with_probe(app, _ProbeCaldav())
    async with _client(app) as client:
        await _admin_household(client)
        sub_id = await _create_sub(client)
        assert (await client.post(f"/v1/calendar/subscriptions/{sub_id}/check")).status_code == 403
