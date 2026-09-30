"""Kontolöschung nach Art. 17 — der Antrag und die Sperre (11-S1c, KONZEPT §5.1).

`users.deleted_at` war bis zu diesem Slice eine **tote Spalte**: nichts im Code las sie. Eine
Löschmarkierung hätte also exakt nichts bewirkt — das Konto wäre weiter benutzbar gewesen.

Der Kern dieses Tests sind deshalb **die fünf Türen**. Es gibt fünf Wege, mit denen jemand eine
Sitzung bekommt: Passwort-Login, Kind-PIN, Passkey, Refresh-Rotation und der Weg über einen
Passwort-Reset-Link. Eine vergessene Tür wäre die ganze Lücke — ein gelöschtes Konto, das über
den Passkey weiter hereinkommt, ist nicht gelöscht. Jeder Weg bekommt hier seinen eigenen Test,
und jeder beweist erst, dass er **vorher funktioniert**.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase

PASSWORD = "ein-hinreichend-langes-passwort"


@pytest.fixture
async def db(pg: PgDatabase, redis_db: None) -> AsyncIterator[None]:
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


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


@pytest.fixture
async def solo(pg: PgDatabase, db: None) -> dict[str, uuid.UUID]:
    """Eine Person, ein eigener Haushalt, ein Kind darin (für den PIN-Weg)."""
    from app.kernel.auth.passwords import hash_password
    from app.modules.accounts import service

    ids = {
        "household": uuid.uuid4(),
        "user": uuid.uuid4(),
        "child": uuid.uuid4(),
        "child_household": uuid.uuid4(),
    }
    conn = await _su(pg)
    try:
        await conn.execute("TRUNCATE households, users, memberships, auth_sessions CASCADE;")
        await conn.execute("INSERT INTO households (id,name) VALUES ($1,'Solo');", ids["household"])
        await conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash) VALUES ($1,$2,'Solo',$3);",
            ids["user"],
            "solo@example.org",
            hash_password(PASSWORD),
        )
        await conn.execute(
            "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,'admin');",
            ids["household"],
            ids["user"],
        )
        # Das Kind lebt in einem EIGENEN Haushalt: „solo" soll wirklich solo heißen. Der Fall
        # „Erwachsener plus nur Kinder" hat einen eigenen Test, weil er eine andere Antwort hat.
        await conn.execute(
            "INSERT INTO households (id,name) VALUES ($1,'Kinderhaushalt');", ids["child_household"]
        )
        await conn.execute(
            "INSERT INTO users (id, username, display_name, pin_hash) "
            "VALUES ($1,'kind','Kind',$2);",
            ids["child"],
            hash_password("1234"),
        )
        await conn.execute(
            "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,'child');",
            ids["child_household"],
            ids["child"],
        )
    finally:
        await conn.close()
    assert service  # der Import oben ist die eigentliche Vorbedingung
    return ids


async def _mark_deleted(pg: PgDatabase, user_id: uuid.UUID) -> None:
    conn = await _su(pg)
    try:
        await conn.execute("UPDATE users SET deleted_at = now() WHERE id = $1;", user_id)
    finally:
        await conn.close()


# --- die fünf Türen ------------------------------------------------------------------------------


async def test_password_login_stops_working(solo: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    # Vorher: es geht.
    assert await service.login(email="solo@example.org", password=PASSWORD)

    await _mark_deleted(pg, solo["user"])

    with pytest.raises(ProblemException) as caught:
        await service.login(email="solo@example.org", password=PASSWORD)
    # Bewusst derselbe Slug wie bei falschem Passwort: ein eigener verriete einem Fremden,
    # dass es dieses Konto gab und dass es gelöscht wird.
    assert caught.value.slug == "invalid_credentials"


async def test_child_pin_login_stops_working(solo: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    assert await service.child_login(
        household_id=solo["child_household"], username="kind", pin="1234"
    )

    await _mark_deleted(pg, solo["child"])

    with pytest.raises(ProblemException):
        await service.child_login(household_id=solo["child_household"], username="kind", pin="1234")


async def test_refresh_rotation_stops_working(solo: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    """Der Gürtel zum Hosenträger. Die Sitzungen werden beim Antrag widerrufen — aber ein
    Refresh-Token, das das Rennen gewinnt, verlängerte den Zugang sonst um dreißig Tage."""
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    first = await service.login(email="solo@example.org", password=PASSWORD)
    rotated = await service.refresh(refresh_token=first.refresh_token)
    assert rotated.refresh_token

    await _mark_deleted(pg, solo["user"])

    with pytest.raises(ProblemException):
        await service.refresh(refresh_token=rotated.refresh_token)


async def test_passkey_login_stops_working(solo: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    """Die fünfte Tür — und die, die man am ehesten vergisst.

    Ein Passkey liegt in einer eigenen Tabelle und überlebt die Löschanfrage dort: er fällt erst
    mit dem Nutzer per ``ON DELETE CASCADE``, also erst nach der Karenz. Ohne Prüfung wäre er
    der bequemste Weg zurück in ein Konto, dessen Löschung gerade läuft.

    Der Test braucht **keine** gültige WebAuthn-Assertion: der Guard steht bewusst **vor** der
    Signaturprüfung. Der Beweis ist deshalb der **Slug** — mit gelöschtem Konto antwortet der Pfad
    `invalid_credentials` (der Guard griff), ohne Löschung `passkey_invalid` (die Signaturprüfung
    lehnte ab). Genau diese Unterscheidung geht verloren, wenn jemand den Guard hinter die
    Verifikation schiebt.
    """
    from app.kernel.auth import webauthn
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    cred_id = "dGVzdC1jcmVkZW50aWFsLWlk"  # base64url, ohne Padding — wie gespeichert
    conn = await _su(pg)
    try:
        await conn.execute(
            "INSERT INTO auth_passkeys (user_id, credential_id, public_key, sign_count, name) "
            "VALUES ($1,$2,'nicht-echt',0,'Testschluessel');",
            solo["user"],
            cred_id,
        )
    finally:
        await conn.close()

    async def _attempt() -> str:
        await webauthn.put_challenge("auth:flow", b"0123456789abcdef")
        with pytest.raises(ProblemException) as caught:
            await service.passkey_auth_finish(
                credential={"id": cred_id, "rawId": cred_id, "response": {}, "type": "public-key"},
                flow_id="flow",
                rp_id="localhost",
                origin="http://localhost",
            )
        return caught.value.slug

    # Vorher: der Pfad kommt bis zur Signaturprüfung.
    assert await _attempt() == "passkey_invalid"

    await _mark_deleted(pg, solo["user"])

    # Nachher: er kommt gar nicht mehr so weit.
    assert await _attempt() == "invalid_credentials"


async def test_password_reset_cannot_revive_the_account(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Ein Reset-Link ist 24 h gültig — lange genug, um eine Löschung zu überholen."""
    from app.kernel.auth.reset import issue_reset_token
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    token = await issue_reset_token(solo["user"])
    await _mark_deleted(pg, solo["user"])

    with pytest.raises(ProblemException) as caught:
        await service.reset_password(token=token, new_password="ein-anderes-langes-passwort")
    assert caught.value.slug == "reset_invalid"


# --- der Antrag ----------------------------------------------------------------------------------


async def test_requesting_deletion_locks_the_account_immediately(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    await service.login(email="solo@example.org", password=PASSWORD)

    await service.request_account_deletion(user_id=solo["user"])

    conn = await _su(pg)
    try:
        marked = await conn.fetchval("SELECT deleted_at FROM users WHERE id = $1;", solo["user"])
        live_sessions = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id = $1 AND revoked_at IS NULL;",
            solo["user"],
        )
    finally:
        await conn.close()

    assert marked is not None, "die Karenz läuft — die Zeile ist markiert, nicht weg"
    assert live_sessions == 0, "alle Sitzungen enden sofort"
    with pytest.raises(ProblemException):
        await service.login(email="solo@example.org", password=PASSWORD)


async def test_requesting_twice_does_not_restart_the_grace_period(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Sonst könnte ein Konto durch wiederholte Anträge unbegrenzt in der Schwebe bleiben."""
    from app.modules.accounts import service

    await service.request_account_deletion(user_id=solo["user"])
    conn = await _su(pg)
    try:
        first = await conn.fetchval("SELECT deleted_at FROM users WHERE id = $1;", solo["user"])
    finally:
        await conn.close()

    await service.request_account_deletion(user_id=solo["user"])

    conn = await _su(pg)
    try:
        second = await conn.fetchval("SELECT deleted_at FROM users WHERE id = $1;", solo["user"])
    finally:
        await conn.close()
    assert first == second


async def test_a_solo_household_does_not_block(solo: dict[str, uuid.UUID]) -> None:
    """„Übertrage zuerst die Admin-Rolle" ist im Ein-Personen-Haushalt unerfüllbar — es gibt
    niemanden. Er darf deshalb nicht aufhalten."""
    from app.modules.accounts import service

    assert await service.account_deletion_blockers(user_id=solo["user"]) == []


async def test_a_household_with_only_children_blocks_with_its_own_reason(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der Fall, der beim Bauen auffiel und den ich zuerst falsch hatte.

    Erwachsener plus nur Kinder: „übertrage zuerst die Rolle" ist genauso unerfüllbar wie im
    Ein-Personen-Haushalt — ein Kind kann nicht Admin werden. Es pauschal als `last_admin` zu
    behandeln, sperrte die Person **für immer** aus ihrem eigenen Löschrecht. Es hält trotzdem auf
    (Kinder ohne Verwaltung zurückzulassen wäre die andere falsche Antwort), aber mit eigenem
    Grund — der auf die Haushaltslöschung wartet.
    """
    from app.modules.accounts import service

    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE memberships SET household_id = $1 WHERE user_id = $2;",
            solo["household"],
            solo["child"],
        )
    finally:
        await conn.close()

    blockers = await service.account_deletion_blockers(user_id=solo["user"])
    assert [b.reason for b in blockers] == ["only_children"]


# --- der Guard, der aufhält ----------------------------------------------------------------------


@pytest.fixture
async def shared(pg: PgDatabase, db: None) -> dict[str, uuid.UUID]:
    """Ein Haushalt mit einem Admin und einem weiteren erwachsenen Mitglied."""
    from app.kernel.auth.passwords import hash_password

    ids = {"household": uuid.uuid4(), "admin": uuid.uuid4(), "member": uuid.uuid4()}
    conn = await _su(pg)
    try:
        await conn.execute("TRUNCATE households, users, memberships, auth_sessions CASCADE;")
        await conn.execute("INSERT INTO households (id,name) VALUES ($1,'WG');", ids["household"])
        for key, role in (("admin", "admin"), ("member", "member")):
            await conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash) VALUES ($1,$2,$3,$4);",
                ids[key],
                f"{key}@example.org",
                key,
                hash_password(PASSWORD),
            )
            await conn.execute(
                "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,$3);",
                ids["household"],
                ids[key],
                role,
            )
    finally:
        await conn.close()
    return ids


async def test_the_last_admin_of_a_shared_household_is_blocked(
    shared: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Ohne sie säßen die Verbliebenen in einem Haushalt fest, den niemand mehr führt."""
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    blockers = await service.account_deletion_blockers(user_id=shared["admin"])
    assert [b.reason for b in blockers] == ["last_admin"]

    with pytest.raises(ProblemException) as caught:
        await service.request_account_deletion(user_id=shared["admin"])
    assert caught.value.slug == "last_admin"

    conn = await _su(pg)
    try:
        marked = await conn.fetchval("SELECT deleted_at FROM users WHERE id = $1;", shared["admin"])
    finally:
        await conn.close()
    assert marked is None, "ein abgelehnter Antrag darf nichts markieren"


async def test_a_plain_member_is_never_blocked(shared: dict[str, uuid.UUID]) -> None:
    """Gegenprobe: der Guard gilt der Admin-Kontinuität, nicht dem Löschen an sich."""
    from app.modules.accounts import service

    assert await service.account_deletion_blockers(user_id=shared["member"]) == []
    await service.request_account_deletion(user_id=shared["member"])


async def test_a_second_admin_removes_the_block(
    shared: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der Weg heraus, den die Fehlermeldung nennt: Rolle übertragen."""
    from app.modules.accounts import service

    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE memberships SET role='admin' WHERE user_id=$1;", shared["member"]
        )
    finally:
        await conn.close()

    assert await service.account_deletion_blockers(user_id=shared["admin"]) == []


# --- der Austritt geschieht sofort, nicht erst mit dem Purge --------------------------------------


async def test_deleting_the_account_leaves_every_household_at_once(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der Fehler, der in der ersten Fassung dieses Slices steckte.

    `request_account_deletion` setzte nur `deleted_at` und widerrief Sitzungen. Damit lief für ein
    **selbst gelöschtes** Konto keiner der vier `member.left`-Handler — und der ICS-Feed-Token
    blieb gültig. Der ist unauthentifiziert, an nichts gebunden und hat kein Ablaufdatum: genau die
    Lücke, die 11-S1a für den Austritt geschlossen hatte, auf dem Nachbarpfad wieder offen.

    Geprüft wird deshalb beides: die Mitgliedschaft ist getombstonet **und** das Ereignis liegt in
    der Outbox. Ohne das Ereignis läuft der Feed-Token-Widerruf nie.
    """
    conn = await _su(pg)
    try:
        await conn.execute("DELETE FROM events_outbox;")
        live_before = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE user_id = $1 AND deleted_at IS NULL;",
            solo["user"],
        )
    finally:
        await conn.close()
    assert live_before == 1, "Vorbedingung: die Mitgliedschaft lebt"

    from app.modules.accounts import service

    await service.request_account_deletion(user_id=solo["user"])

    conn = await _su(pg)
    try:
        live_after = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE user_id = $1 AND deleted_at IS NULL;",
            solo["user"],
        )
        events = await conn.fetch(
            "SELECT type, payload FROM events_outbox WHERE type = 'member.left';"
        )
    finally:
        await conn.close()

    assert live_after == 0, "die Mitgliedschaft muss sofort enden, nicht erst nach der Karenz"
    assert len(events) == 1
    assert events[0]["payload"] is not None


async def test_leaving_is_idempotent_across_repeated_requests(
    solo: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Ein zweiter Antrag darf kein zweites `member.left` erzeugen — die Handler sind zwar
    idempotent, aber ein Ereignis ohne Anlass ist trotzdem eine Lüge im Protokoll."""
    conn = await _su(pg)
    try:
        await conn.execute("DELETE FROM events_outbox;")
    finally:
        await conn.close()

    from app.modules.accounts import service

    await service.request_account_deletion(user_id=solo["user"])
    await service.request_account_deletion(user_id=solo["user"])

    conn = await _su(pg)
    try:
        count = await conn.fetchval(
            "SELECT count(*) FROM events_outbox WHERE type = 'member.left';"
        )
    finally:
        await conn.close()
    assert count == 1
