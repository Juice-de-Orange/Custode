"""Die Refresh-Rotation leitet den Haushalts-Scope aus der Datenbank ab (11-S1g).

`POST /v1/auth/refresh` mintete das neue Access-Token bis hierher mit genau dem, was in Redis unter
`active_household:<family>` stand — 30 Tage lang (die Lebensdauer des Refresh-Tokens), ohne
Rückfrage. Weder ein aufgelöster Haushalt noch eine tote Mitgliedschaft noch eine geänderte Rolle
kamen dort an.

Zwei Wege führten hinein:

1. **Der Zustand nach dem Rennen aus 11-S1e.** `remove_member` und `dissolve_household` widerrufen
   die Sitzungen, aber ihre eigene `maint`-Transaktion committet **vor** der äußeren. Wer sich in
   diesem Fenster anmeldet, hält danach eine *lebende* Sitzung samt Merkzettel auf einen Haushalt,
   in dem er nicht mehr Mitglied ist. Ein Test kann dieses Fenster nicht zuverlässig treffen, also
   wird der Zustand hergestellt, den es hinterlässt: Sitzung lebt, Merkzettel steht, Mitgliedschaft
   getombstonet. **Damit das keine Fiktion bleibt**, prüft
   `test_the_real_removal_endpoint_leaves_no_session_to_rotate` den echten Endpunkt daneben — er
   belegt, dass im Regelfall gar nichts zu rotieren übrig bleibt, und grenzt damit ein, wofür der
   konstruierte Zustand überhaupt steht.
2. **Der Rollenwechsel**, und der braucht gar kein Rennen. `change_role` widerruft — anders als
   `remove_member` — keine Sitzungen. Ein herabgestufter Admin blieb Admin, solange er rotierte.

Ein dritter Test (`…_when_the_household_was_dissolved`) prüft eine Konstellation, die es in
Produktion **nicht** gibt — Mitgliedschaft lebt, Haushalt tot. Das ist Absicht und dort begründet:
`get_active_role` trägt die Haushalts-Bedingung eigenständig (ADR-0085 §6), und ein Zweig ohne Test
verschwindet beim nächsten Aufräumen.

**Jeder Test zeigt erst das Vorher, und zwar als Wirkung, nicht als Feld.** „Nachher kein Zugriff"
besteht auch bei kaputtem Seed; und `GET /v1/auth/me` liest nur dasselbe Token zurück, das schon in
der Rotationsantwort steht. Der Nachweis läuft deshalb über `_visible_members` — eine RLS-gescopte
Route: „Scope weg" muss „**Daten** weg" heißen. Dazu je eine Gegenprobe, dass der Berechtigte
weiterhin durchkommt.

Ohne Docker übersprungen — **und das ist die stille Gefahr dieser Datei**: ohne Docker laufen null
von zehn Fällen, und der Job wird trotzdem grün (Roadmap Phase 11, „das stille Überspringen").

"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.kernel.auth import access
from app.kernel.auth.context import Role
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_AT = "custode_at"
_RT = "custode_rt"
_CSRF = "custode_csrf"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.de"


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


async def _register(client: AsyncClient) -> dict[str, object]:
    resp = await client.post(
        "/v1/auth/register",
        json={"email": _email(), "password": _PASSWORD, "display_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _rotate(client: AsyncClient) -> dict[str, object]:
    """Eine Rotation durchführen und die Sitzungsantwort zurückgeben."""
    resp = await client.post("/v1/auth/refresh", headers=_csrf(client))
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _visible_members(client: AsyncClient) -> int:
    """Wie viele Mitglieder die Sitzung **tatsächlich sieht** — der Wirkungsnachweis.

    `/v1/auth/me` liest nur das Token zurück; ein Test, der bloß dort `household_id: null`
    prüft, bestätigt die Repräsentation, nicht ihre Folge. Diese Route hängt dagegen an einer
    RLS-gescopten Session: fehlt der Haushalt, filtert die **Datenbank** auf null Zeilen.
    „Scope weg" muss „Daten weg" heißen.
    """
    resp = await client.get("/v1/household/members")
    assert resp.status_code == 200, resp.text
    return len(resp.json())


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    """Superuser-Verbindung — für Eingriffe, die die App bewusst nicht anbietet."""
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


async def _family_of(pg: PgDatabase, user_id: str) -> uuid.UUID:
    conn = await _su(pg)
    try:
        row = await conn.fetchrow(
            "SELECT family_id FROM auth_sessions WHERE user_id = $1 AND revoked_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1;",
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()
    assert row is not None, "keine lebende Sitzung — der Aufbau des Tests stimmt nicht"
    return uuid.UUID(str(row["family_id"]))


async def _household_with_member(
    app_obj: FastAPI, admin: AsyncClient, member: AsyncClient
) -> tuple[str, dict[str, object], dict[str, object]]:
    """Ein Haushalt, ein Admin, ein beigetretenes Mitglied — beide angemeldet."""
    admin_body = await _register(admin)
    created = await admin.post("/v1/households", json={"name": "H"}, headers=_csrf(admin))
    assert created.status_code == 201, created.text
    household_id = str(created.json()["household_id"])
    code = (await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))).json()["code"]
    member_body = await _register(member)
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    return household_id, admin_body, member_body


# ------------------------------------------------------------------ tote Mitgliedschaft


async def test_rotation_drops_scope_when_the_membership_died_unnoticed(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Der Zustand nach dem Rennen aus 11-S1e: Sitzung lebt, Mitgliedschaft nicht mehr."""
    async with _client(app) as admin, _client(app) as member:
        household_id, _, member_body = await _household_with_member(app, admin, member)

        # Vorher: die Rotation TRÄGT den Haushalt — und die Sitzung SIEHT den Haushalt.
        # Ohne beide Belege prüft der Rest nichts.
        before = await _rotate(member)
        assert before["household_id"] == household_id
        assert before["role"] == "member"
        assert await _visible_members(member) == 2

        # Die Mitgliedschaft stirbt, ohne dass jemand die Sitzung anfasst — genau das hinterlässt
        # das Fenster zwischen dem Sitzungs-Widerruf und dem Commit des Tombstones.
        conn = await _su(pg)
        try:
            await conn.execute(
                "UPDATE memberships SET deleted_at = now() WHERE user_id = $1;",
                uuid.UUID(str(member_body["user_id"])),
            )
        finally:
            await conn.close()

        # Nachher: dieselbe Sitzung rotiert weiter — aber ohne Scope.
        after = await _rotate(member)
        assert after["household_id"] is None
        assert after["role"] is None

        # Und der Verlust ist echt, nicht bloß ein Feld im JSON: die Datenbank liefert nichts mehr.
        assert await _visible_members(member) == 0


async def test_rotation_clears_the_redis_memo_after_a_scope_loss(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Der Merkzettel darf nicht überleben — sonst behaupten Redis und `/me` Verschiedenes."""
    async with _client(app) as admin, _client(app) as member:
        household_id, _, member_body = await _household_with_member(app, admin, member)
        family_id = await _family_of(pg, str(member_body["user_id"]))

        # Vorher: der Merkzettel steht — und er zeigt auf DIESEN Haushalt. Ohne die zweite
        # Bedingung genügte irgendein Merkzettel irgendeiner Familie.
        assert await access.get_active_household(family_id) == (
            uuid.UUID(household_id),
            Role.member,
        )

        conn = await _su(pg)
        try:
            await conn.execute(
                "UPDATE memberships SET deleted_at = now() WHERE user_id = $1;",
                uuid.UUID(str(member_body["user_id"])),
            )
        finally:
            await conn.close()

        # Der Scope fällt — und der Merkzettel fällt mit. Beides prüfen: ein Räumen ohne
        # Scope-Verlust wäre genauso falsch wie ein Scope-Verlust ohne Räumen.
        after = await _rotate(member)
        assert after["household_id"] is None
        assert await access.get_active_household(family_id) is None


async def test_a_redis_read_failure_does_not_destroy_a_valid_scope(
    app: FastAPI, pg: PgDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Aussetzer darf keinen bleibenden Schaden hinterlassen.

    `get_active_household` ist fail-closed: bei einem Redis-Lesefehler liefert es `None`, genau
    wie bei „kein Merkzettel". Räumte die Rotation daraufhin, machte **ein einziger** Aussetzer
    aus einer vorübergehenden Störung einen dauerhaften Verlust des Haushalts-Kontexts — die
    Person landete in der Auswahl, obwohl sich an ihrer Mitgliedschaft nichts geändert hat.
    """
    async with _client(app) as admin, _client(app) as member:
        household_id, _, member_body = await _household_with_member(app, admin, member)
        family_id = await _family_of(pg, str(member_body["user_id"]))
        assert await access.get_active_household(family_id) is not None

        # Genau einen Lesevorgang scheitern lassen — so, wie Redis es täte.
        async def _boom(_family: uuid.UUID) -> tuple[uuid.UUID, Role] | None:
            return None

        monkeypatch.setattr(access, "get_active_household", _boom)
        after = await _rotate(member)
        assert after["household_id"] is None  # diese eine Rotation bleibt scope-los, das ist ok
        monkeypatch.undo()

        # Entscheidend: der Merkzettel steht noch, die nächste Rotation trägt wieder.
        assert await access.get_active_household(family_id) == (
            uuid.UUID(household_id),
            Role.member,
        )
        recovered = await _rotate(member)
        assert recovered["household_id"] == household_id
        assert await _visible_members(member) == 2


# ------------------------------------------------------------------ aufgelöster Haushalt


async def test_rotation_drops_scope_when_the_household_was_dissolved(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Die zweite Bedingung in `get_active_role`, isoliert: Mitgliedschaft lebt, Haushalt tot.

    **Diese Konstellation ist in Produktion nicht erreichbar, und das ist der Punkt.**
    `households.deleted_at` hat genau einen Schreiber — `dissolve_household` —, und der tombstonet
    die Mitgliedschaften in **derselben** Transaktion; kein Leser sieht je das eine ohne das
    andere. Der Test stellt den Zustand künstlich her, weil `get_active_role` die
    Haushalts-Bedingung ausdrücklich **eigenständig** trägt (ADR-0085 §6: „eine Sperre, die an
    einem vorherigen Schritt hängt, ist keine"). Ohne diesen Test wäre der Zweig unbelegt, und
    niemand merkte es, wenn ihn jemand als redundant entfernte.

    Was er ausdrücklich **nicht** belegt: das Rennen aus 11-S1e. Dessen Zustand ist eine tote
    *Mitgliedschaft* bei lebender Sitzung — der steht im Nachbartest.
    """
    async with _client(app) as admin, _client(app) as member:
        household_id, _, _ = await _household_with_member(app, admin, member)

        before = await _rotate(member)
        assert before["household_id"] == household_id
        assert await _visible_members(member) == 2

        conn = await _su(pg)
        try:
            await conn.execute(
                "UPDATE households SET deleted_at = now() WHERE id = $1;",
                uuid.UUID(household_id),
            )
            lives = await conn.fetchval(
                "SELECT count(*) FROM memberships WHERE household_id = $1 AND deleted_at IS NULL;",
                uuid.UUID(household_id),
            )
        finally:
            await conn.close()
        # Der Beleg, dass wirklich die Haushalts-Bedingung greift und nicht die Mitgliedschaft.
        assert lives == 2

        after = await _rotate(member)
        assert after["household_id"] is None
        assert after["role"] is None
        assert await _visible_members(member) == 0


async def test_the_real_removal_endpoint_leaves_no_session_to_rotate(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Die Prämisse des Slices gegenprüfen, statt sie zu behaupten.

    Die Nachbartests stellen den Zustand „lebende Sitzung, tote Mitgliedschaft" per SQL her, weil
    das Rennfenster in 11-S1e nicht zuverlässig zu treffen ist. Ohne diesen Test bliebe offen, was
    der **echte** Endpunkt tut — und die ganze Datei prüfte eine Konstruktion, deren Verhältnis
    zur Wirklichkeit niemand nachgesehen hat.

    Belegt wird hier der Gürtel aus 11-S1a: `DELETE /v1/household/members/{id}` widerruft alle
    Sitzungen, es bleibt gar nichts zu rotieren. Der Hosenträger (die Ableitung) ist für den
    Regelfall also gar nicht nötig — nur für das Fenster daneben.
    """
    async with _client(app) as admin, _client(app) as member:
        _, _, member_body = await _household_with_member(app, admin, member)
        # Vorher: das Mitglied ist da und kann rotieren.
        assert await _visible_members(member) == 2
        assert (await _rotate(member))["household_id"] is not None

        members = (await admin.get("/v1/household/members")).json()
        by_user = {m["user_id"]: m for m in members}
        removed = await admin.delete(
            f"/v1/household/members/{by_user[str(member_body['user_id'])]['membership_id']}",
            headers=_csrf(admin),
        )
        assert removed.status_code == 204, removed.text

        # Nachher: das Access-Token ist tot UND die Rotation wird abgewiesen — nicht scope-los
        # beantwortet. Der Unterschied ist der ganze Grund, warum es beide Mechanismen gibt.
        assert (await member.get("/v1/auth/me")).status_code == 401
        rejected = await member.post("/v1/auth/refresh", headers=_csrf(member))
        assert rejected.status_code == 401, rejected.text


# ------------------------------------------------------------------ Rollenwechsel


async def test_demotion_takes_effect_without_anyone_touching_the_session(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Der Fall ohne Rennen: `change_role` widerruft keine Sitzungen — trotzdem endet die Rolle."""
    async with _client(app) as first, _client(app) as second:
        household_id, first_body, second_body = await _household_with_member(app, first, second)

        # `second` zum Admin machen, damit die Admin-Kontinuität die Herabstufung von `first`
        # gleich zulässt.
        members = (await first.get("/v1/household/members")).json()
        by_user = {m["user_id"]: m for m in members}
        promote = await first.patch(
            f"/v1/household/members/{by_user[str(second_body['user_id'])]['membership_id']}",
            json={"role": "admin"},
            headers=_csrf(first),
        )
        assert promote.status_code == 200
        # Die Beförderung entwertet das Token von `second` — sonst trüge es weiter „member".
        # Genau das ist der Punkt dieses Slices, hier von der anderen Seite: `second` muss einmal
        # rotieren, bevor er handeln kann.
        assert (await second.get("/v1/auth/me")).status_code == 401
        assert (await _rotate(second))["role"] == "admin"

        # Vorher: `first` ist Admin und kommt durch eine Admin-Route.
        assert (await _rotate(first))["role"] == "admin"
        opened = await first.post("/v1/household/invites", json={}, headers=_csrf(first))
        assert opened.status_code == 201, opened.text

        # `second` stuft `first` herab. Es wird KEINE Sitzung widerrufen.
        demote = await second.patch(
            f"/v1/household/members/{by_user[str(first_body['user_id'])]['membership_id']}",
            json={"role": "member"},
            headers=_csrf(second),
        )
        assert demote.status_code == 200
        conn = await _su(pg)
        try:
            revoked = await conn.fetchval(
                "SELECT count(*) FROM auth_sessions WHERE user_id = $1 AND revoked_at IS NOT NULL;",
                uuid.UUID(str(first_body["user_id"])),
            )
        finally:
            await conn.close()
        # Auf `count(revoked_at IS NULL) >= 1` zu prüfen wäre wertlos: die Rotation legt je Lauf
        # eine NEUE Zeile an und lässt die alte unwiderrufen stehen — es gibt also immer mehrere.
        # Gefragt ist die Gegenrichtung: es wurde **keine einzige** Sitzung widerrufen.
        assert revoked == 0, "change_role darf keine Sitzung widerrufen, nur Tokens entwerten"

        # Das alte Access-Token ist entwertet: die Rechte gelten nicht bis zum TTL weiter.
        assert (await first.get("/v1/auth/me")).status_code == 401

        # Die Rotation holt die Rolle aus der Datenbank — der Merkzettel sagt weiterhin „admin".
        after = await _rotate(first)
        assert after["role"] == "member"
        # Und zwar DERSELBE Haushalt: eine Herabstufung darf den Kontext nicht mit wegnehmen.
        assert after["household_id"] == household_id
        assert await _visible_members(first) == 2

        # Und sie beißt: dieselbe Route antwortet jetzt 403.
        refused = await first.post("/v1/household/invites", json={}, headers=_csrf(first))
        assert refused.status_code == 403


async def test_demotion_burns_the_affected_persons_tokens_and_only_those(app: FastAPI) -> None:
    """Beide Hälften der Zusage in einem Test — sonst deckt keiner die falsche Richtung ab.

    Ein zu enger Burn ließe die alten Rechte bis zum Token-Ablauf stehen; ein zu weiter meldete
    den handelnden Admin mitten im Vorgang ab.
    """
    async with _client(app) as first, _client(app) as second:
        _, first_body, second_body = await _household_with_member(app, first, second)
        members = (await first.get("/v1/household/members")).json()
        by_user = {m["user_id"]: m for m in members}
        await first.patch(
            f"/v1/household/members/{by_user[str(second_body['user_id'])]['membership_id']}",
            json={"role": "admin"},
            headers=_csrf(first),
        )
        # `second` wurde soeben selbst befördert — sein Token ist entwertet, also einmal rotieren.
        assert (await _rotate(second))["role"] == "admin"
        # Vorher: `first` kommt mit seinem Token durch.
        assert (await first.get("/v1/auth/me")).status_code == 200

        await second.patch(
            f"/v1/household/members/{by_user[str(first_body['user_id'])]['membership_id']}",
            json={"role": "member"},
            headers=_csrf(second),
        )
        # Der Betroffene: Token tot.
        assert (await first.get("/v1/auth/me")).status_code == 401
        # Der Handelnde: Token lebt, Rolle unverändert.
        me = await second.get("/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "admin"


async def test_promotion_reaches_the_session_too(app: FastAPI) -> None:
    """Die Ableitung ist keine Einbahnstraße: eine Beförderung wirkt genauso schnell.

    Wichtig, weil ein Fix, der nur Rechte *entzieht*, eine zweite Wahrheit einführt — dann hinge
    die Rolle davon ab, in welche Richtung sie sich zuletzt bewegt hat.
    """
    async with _client(app) as admin, _client(app) as member:
        _, _, member_body = await _household_with_member(app, admin, member)
        assert (await _rotate(member))["role"] == "member"
        # Die negative Basislinie: ohne sie belegte das 201 unten nur „Admins dürfen einladen",
        # nicht „vorher durfte er es nicht". Ein Endpunkt ohne `AdminPrincipal` wäre sonst grün.
        refused = await member.post("/v1/household/invites", json={}, headers=_csrf(member))
        assert refused.status_code == 403, refused.text

        members = (await admin.get("/v1/household/members")).json()
        by_user = {m["user_id"]: m for m in members}
        await admin.patch(
            f"/v1/household/members/{by_user[str(member_body['user_id'])]['membership_id']}",
            json={"role": "admin"},
            headers=_csrf(admin),
        )
        assert (await _rotate(member))["role"] == "admin"
        opened = await member.post("/v1/household/invites", json={}, headers=_csrf(member))
        assert opened.status_code == 201


# ------------------------------------------------------------------ Gegenproben


async def test_an_uninvolved_member_keeps_rotating_with_their_scope(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Ohne diese Gegenprobe belegen die Tests oben nur, dass irgendetwas kaputtgeht."""
    async with _client(app) as admin, _client(app) as member, _client(app) as bystander:
        household_id, _, member_body = await _household_with_member(app, admin, member)
        code = (await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))).json()[
            "code"
        ]
        await _register(bystander)
        joined = await bystander.post(
            "/v1/households/join", json={"code": code}, headers=_csrf(bystander)
        )
        assert joined.status_code == 201

        # Vorher auf BEIDEN Seiten. Ohne den Beleg für `bystander` wäre seine Zeile unten auch
        # dann grün, wenn er nie einen Scope gehabt hätte; ohne den für `member` bewiese das
        # UPDATE nichts.
        assert (await _rotate(member))["household_id"] == household_id
        assert (await _rotate(bystander))["household_id"] == household_id

        conn = await _su(pg)
        try:
            await conn.execute(
                "UPDATE memberships SET deleted_at = now() WHERE user_id = $1;",
                uuid.UUID(str(member_body["user_id"])),
            )
        finally:
            await conn.close()

        assert (await _rotate(member))["household_id"] is None
        assert await _visible_members(member) == 0
        still = await _rotate(bystander)
        assert still["household_id"] == household_id
        assert still["role"] == "member"
        # Der Unbeteiligte sieht weiterhin Daten — und der Entzug hat seinen Merkzettel nicht
        # mitgerissen. Drei Mitglieder, eines davon getombstonet: er sieht die zwei lebenden.
        assert await _visible_members(bystander) == 2


async def test_rotation_without_a_memo_does_not_hand_out_a_new_scope(
    app: FastAPI, pg: PgDatabase
) -> None:
    """Eine Rotation darf einen Scope bestätigen, aber keinen neuen vergeben.

    Wer sich anmeldet und genau einem Haushalt angehört, wird beim **Login** dorthin gescopt
    (`resolve_sole_household`, P8-Prod-QA-Befund #132). Fehlt der Merkzettel, darf die Rotation das
    **nicht** nachholen: sonst käme der Scope nach jedem Verlust im nächsten Takt zurück, und der
    Entzug hätte fünfzehn Minuten gehalten.
    """
    async with _client(app) as admin, _client(app) as member:
        household_id, _, member_body = await _household_with_member(app, admin, member)
        family_id = await _family_of(pg, str(member_body["user_id"]))

        # Vorher: mit Merkzettel trägt die Rotation den Haushalt.
        assert (await _rotate(member))["household_id"] == household_id

        # Nur den Merkzettel abräumen — die Mitgliedschaft bleibt ausdrücklich bestehen.
        await access.set_active_household(family_id, None, None)

        after = await _rotate(member)
        assert after["household_id"] is None
        assert after["role"] is None

        # Gegenprobe, dass wirklich nur der Merkzettel fehlte: der Wechsel führt zurück.
        back = await member.post(f"/v1/households/{household_id}/switch", headers=_csrf(member))
        assert back.status_code == 200
        assert back.json()["household_id"] == household_id
