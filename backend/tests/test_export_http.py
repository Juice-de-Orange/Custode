"""The two download routes end to end (Testcontainers PG 18) — Art. 15 / Art. 20.

What the unit tests cannot show: that the *route* keeps the promises the collector makes. A child
may export themselves (the right belongs to the person), a member may not export the household
(that file describes everyone), and the ZIP that comes back is a real archive with a manifest that
names what it withheld.

Skipped without Docker.
"""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from collections.abc import AsyncIterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase

SECRET_TOKENS = "v1:fremdes-oura-token-darf-nie-raus"


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


async def _seed(pg: PgDatabase) -> dict[str, uuid.UUID]:
    ids = {
        "household": uuid.uuid4(),
        "admin": uuid.uuid4(),
        "member": uuid.uuid4(),
        "child": uuid.uuid4(),
    }
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute("TRUNCATE households, users, memberships CASCADE;")
        await conn.execute("TRUNCATE wearable_connections, recipes, notes CASCADE;")
        await conn.execute(
            "INSERT INTO households (id, name) VALUES ($1,'Testhaushalt');", ids["household"]
        )
        for key, role in (("admin", "admin"), ("member", "member"), ("child", "child")):
            await conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES ($1,$2,$3);",
                ids[key],
                f"{key}@example.org",
                key,
            )
            await conn.execute(
                "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,$3);",
                ids["household"],
                ids[key],
                role,
            )
        await conn.execute(
            "INSERT INTO wearable_connections "
            "(household_id, member_id, provider, tokens_enc) VALUES ($1,$2,'oura',$3);",
            ids["household"],
            ids["member"],
            SECRET_TOKENS,
        )
        await conn.execute(
            "INSERT INTO recipes (household_id, title) VALUES ($1,'Linsensuppe');",
            ids["household"],
        )
        await conn.execute(
            "INSERT INTO notes (household_id, author_id, title, body_md) "
            "VALUES ($1,$2,'Meine Notiz','...');",
            ids["household"],
            ids["member"],
        )
        # Der Consent des Mitglieds zu Herzfrequenz-Daten — die blosse Existenz dieser Zeile ist
        # eine Aussage ueber seine Gesundheit.
        await conn.execute(
            "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
            "VALUES ($1,$2,'wearable_heartrate','grant',$2);",
            ids["household"],
            ids["member"],
        )
        # Ein privater Termin des Mitglieds und ein geteilter des Haushalts. Der private ist fuer
        # den Admin ueber jede API-Route ein 404 (ADR-0040) — der Export darf das nicht aushebeln.
        for layer, title in (("personal", "Onkologie-Nachsorge"), ("household", "Grillabend")):
            await conn.execute(
                "INSERT INTO calendar_events "
                "(household_id, owner_id, title, starts_at, ends_at, layer) "
                "VALUES ($1,$2,$3,now(),now() + interval '1 hour',$4);",
                ids["household"],
                ids["member"],
                title,
                layer,
            )
        # Ein CalDAV-Abo: die URL traegt den Fremdsystem-Benutzernamen im Pfad.
        await conn.execute(
            "INSERT INTO external_calendar_subscriptions "
            "(household_id, member_id, label, caldav_url) VALUES ($1,$2,'Therapie',$3);",
            ids["household"],
            ids["member"],
            "https://cloud.example/remote.php/dav/calendars/m-privat/therapie/",
        )
        # Ein Brief des Mitglieds an ein Kind — der Admin ist nicht adressiert.
        await conn.execute(
            "INSERT INTO letters (household_id, from_id, to_ids, subject, body_md) "
            "VALUES ($1,$2,$3,'Nur fuer dich','vertraulich');",
            ids["household"],
            ids["member"],
            [ids["child"]],
        )
        # Persoenlicher Zuruf und eine Feedback-Meldung.
        await conn.execute(
            "INSERT INTO captures (household_id, member_id, raw_text) VALUES ($1,$2,$3);",
            ids["household"],
            ids["member"],
            "Termin beim Anwalt notieren",
        )
        await conn.execute(
            "INSERT INTO feedback (household_id, author_id, category, message) "
            "VALUES ($1,$2,'problem',$3);",
            ids["household"],
            ids["member"],
            "Der Admin aendert staendig meine Aufgaben",
        )
    finally:
        await conn.close()
    return ids


@pytest.fixture
async def app_client(db: None) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = application  # type: ignore[attr-defined]
        yield client


def _as(client: AsyncClient, ids: dict[str, uuid.UUID], who: str, role: str) -> None:
    """Install a principal without going through the login flow — this file tests the export
    routes, not authentication (which has its own suite)."""
    from app.kernel.auth.context import Principal, Role, set_principal
    from app.kernel.auth.dependencies import get_current_principal

    principal = Principal(
        user_id=ids[who],
        family_id=uuid.uuid4(),
        household_id=ids["household"],
        role=Role(role),
    )

    async def _override() -> Principal:
        # Two things matter here. The real dependency BINDS the principal to the request context;
        # the sibling scoped session reads it to set the RLS scope, so an override that merely
        # returns the object leaves every query seeing zero rows. And it must be ``async``:
        # FastAPI runs a sync dependency in a threadpool, where the contextvar we set never
        # reaches the session.
        set_principal(principal)
        return principal

    client.app.dependency_overrides[get_current_principal] = _override  # type: ignore[attr-defined]


def _open(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


# --- shape --------------------------------------------------------------------------------------


async def test_personal_export_returns_a_real_zip(app_client: AsyncClient, pg: PgDatabase) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/me/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in response.headers["content-disposition"]
    # A file full of personal data must never sit in a shared cache.
    assert response.headers["cache-control"] == "no-store"

    archive = _open(response.content)
    names = set(archive.namelist())
    assert "manifest.json" in names
    assert "LIESMICH.txt" in names
    assert "data/notes.json" in names


async def test_manifest_names_what_was_withheld(app_client: AsyncClient, pg: PgDatabase) -> None:
    """The export states its own gaps — that is what separates it from a partial dump."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    manifest = json.loads(_open(response.content).read("manifest.json"))

    assert manifest["scope"] == "household"
    assert "users.password_hash" in manifest["withheld_columns"]
    assert "wearable_connections.tokens_enc" in manifest["withheld_columns"]
    # Excluded tables come with their reason, not just their name.
    assert manifest["excluded_tables"]["audit_log"]
    assert len(manifest["excluded_tables"]["audit_log"]) > 20


# --- authorisation ------------------------------------------------------------------------------


async def test_a_child_may_export_themselves(app_client: AsyncClient, pg: PgDatabase) -> None:
    """The subject right belongs to the person, not to a role. Children are excluded from
    wearables and the vault — but not from knowing what is stored about them."""
    ids = await _seed(pg)
    _as(app_client, ids, "child", "child")

    response = await app_client.get("/v1/me/export")

    assert response.status_code == 200


async def test_a_member_may_not_export_the_household(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """That archive describes everyone in the household, so it is the admin's to pull."""
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/household/export")

    assert response.status_code == 403


async def test_a_child_may_not_export_the_household(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "child", "child")
    assert (await app_client.get("/v1/household/export")).status_code == 403


async def test_export_requires_authentication(app_client: AsyncClient, pg: PgDatabase) -> None:
    await _seed(pg)
    for path in ("/v1/me/export", "/v1/household/export"):
        assert (await app_client.get(path)).status_code == 401


# --- the Art. 9 promise, through the route ------------------------------------------------------


async def test_the_household_zip_carries_no_foreign_health_token(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """The end-to-end version of the collector's core test: search the whole archive, every entry,
    for a co-member's token. Member-scoped RLS keeps the row out; redaction would have caught the
    value even if it had not."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    archive = _open(response.content)
    blob = b"".join(archive.read(name) for name in archive.namelist())

    assert SECRET_TOKENS.encode() not in blob


async def test_admin_household_export_omits_the_other_members_wearables(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    rows = json.loads(_open(response.content).read("data/wearable_connections.json"))

    assert rows == []


async def test_the_member_gets_their_own_wearable_row(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Counterpart to the test above: the data is not gone, it is theirs. Without this the
    previous assertion could pass simply because the export is broken."""
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/me/export")
    rows = json.loads(_open(response.content).read("data/wearable_connections.json"))

    assert len(rows) == 1
    assert rows[0]["member_id"] == str(ids["member"])
    assert rows[0]["tokens_enc"] == "<redaktiert>"


# --- scope difference ---------------------------------------------------------------------------


async def test_personal_export_omits_shared_rows_and_says_why(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/me/export")
    archive = _open(response.content)
    manifest = json.loads(archive.read("manifest.json"))

    assert "data/recipes.json" not in archive.namelist()
    assert "recipes" in manifest["skipped_tables"]
    assert "LIESMICH.txt" in archive.namelist()
    assert "Haushalts-Export" in archive.read("LIESMICH.txt").decode()


async def test_household_export_contains_the_shared_rows(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    rows = json.loads(_open(response.content).read("data/recipes.json"))

    assert [row["title"] for row in rows] == ["Linsensuppe"]


# --- logging ------------------------------------------------------------------------------------


async def test_the_log_line_carries_counts_but_no_content(
    app_client: AsyncClient, pg: PgDatabase, captured_logs: list[dict[str, object]]
) -> None:
    """An export touches every table; a chatty log line here would be a PII incident of its own."""
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    await app_client.get("/v1/me/export")

    built = [entry for entry in captured_logs if entry.get("event") == "export_built"]
    assert built, "der Export sollte genau eine Zeile loggen"
    assert set(built[0]) >= {"scope", "rows", "bytes"}
    assert "Meine Notiz" not in json.dumps(built[0], default=str)


# --- Consent-Metadaten (N-2, ADR-0081 §6) --------------------------------------------------------


async def test_household_export_hides_a_co_members_health_consent(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Die Wearable-TABELLEN haelt die mitglieds-gescopte RLS fern — die consents-Tabelle nicht.

    Deren RLS ist haushaltsweit (Migration 0013), und ein Consent-Typ heisst `wearable_heartrate`.
    Die blosse Existenz der Zeile verraet dem Admin, dass der Mitbewohner einen Tracker traegt und
    welche Werte er teilt. ADR-0081 §6 hat exakt diese Metadaten-Klasse als Domain-Event
    abgelehnt; der Export darf sie nicht durch die Hintertuer doch herausgeben. Deshalb ist
    `consents` als `subject_scoped` markiert. Ohne diese Markierung ist dieser Test rot.
    """
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    rows = json.loads(_open(response.content).read("data/consents.json"))

    assert [r for r in rows if r["subject_user_id"] == str(ids["member"])] == []
    blob = _open(response.content).read("data/consents.json").decode()
    assert "wearable_heartrate" not in blob


async def test_the_member_still_sees_their_own_consent(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Gegenprobe: die Zeile ist nicht verschwunden, sie gehoert ihrer Person."""
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/me/export")
    rows = json.loads(_open(response.content).read("data/consents.json"))

    assert [r["type"] for r in rows] == ["wearable_heartrate"]


# --- app-seitige Eigentuemer-Grenzen, die die RLS NICHT zieht -----------------------------------
# Die adversariale Pruefung dieses Slices fand sie: der Export las jede Tabelle ganz, sobald RLS
# sie durchliess. Dieses Repo zieht aber viele Grenzen im Service-Layer. Seither ist `shared` die
# ausdrueckliche Ausnahme statt der Voreinstellung; die folgenden Tests sind ohne sie alle rot.


async def test_household_export_hides_a_co_members_personal_calendar_entry(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """ADR-0040: ein `personal`-Termin ist fuer Mitbewohner ein 404. Die RLS auf calendar_events
    ist rein haushaltsweit (Migration 0032) — die Grenze zieht ausschliesslich der Service. Ohne
    `shared_when` waere der Export der einzige Pfad im System, der daran vorbeigeht. Und weil
    CalDAV-Spiegel als `personal` angelegt werden, ginge es um komplette Privatkalender."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    response = await app_client.get("/v1/household/export")
    titles = [
        r["title"] for r in json.loads(_open(response.content).read("data/calendar_events.json"))
    ]

    assert "Onkologie-Nachsorge" not in titles
    # Gegenprobe: der geteilte Termin ist sehr wohl drin, sonst waere die Zusicherung wertlos.
    assert "Grillabend" in titles


async def test_the_owner_still_gets_their_personal_calendar_entry(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    response = await app_client.get("/v1/me/export")
    titles = [
        r["title"] for r in json.loads(_open(response.content).read("data/calendar_events.json"))
    ]

    assert "Onkologie-Nachsorge" in titles


async def test_household_export_hides_a_co_members_caldav_subscription(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Das Modell sagt woertlich zu, dass auch ein ADMIN diese Zeile nie sieht. `creds_enc` ist
    redigiert — aber die URL traegt den Fremdsystem-Benutzernamen, also genau die PII, die im
    Ciphertext bleiben sollte."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    blob = _open((await app_client.get("/v1/household/export")).content)
    text = b"".join(blob.read(n) for n in blob.namelist()).decode("utf-8", "replace")

    assert "m-privat" not in text
    assert "Therapie" not in text


async def test_household_export_hides_a_letter_the_admin_is_not_addressed_in(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    blob = _open((await app_client.get("/v1/household/export")).content)
    text = b"".join(blob.read(n) for n in blob.namelist()).decode("utf-8", "replace")

    assert "vertraulich" not in text


async def test_household_export_hides_captures_and_feedback_of_others(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Der Zuruf ist ein persoenlicher Posteingang; der Meldekanal richtet sich womoeglich GEGEN
    den Admin — ihn dort mitlesen zu lassen, zerstoert den Kanal."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    blob = _open((await app_client.get("/v1/household/export")).content)
    text = b"".join(blob.read(n) for n in blob.namelist()).decode("utf-8", "replace")

    assert "Anwalt" not in text
    assert "aendert staendig meine Aufgaben" not in text


async def test_the_manifest_names_the_narrowing_instead_of_hiding_it(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Zusage 4 des Slices: nichts faellt still weg. "Fehlt ganz" und "auf dich eingeengt" sind
    verschiedene Antworten auf die Frage, ob das alles ist."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    archive = _open((await app_client.get("/v1/household/export")).content)
    manifest = json.loads(archive.read("manifest.json"))

    assert "consents" in manifest["narrowed_tables"]
    assert "letters" in manifest["narrowed_tables"]
    assert "eingeengt" in manifest["narrowed_tables"]["consents"]
    assert "Auf dich eingeengt" in archive.read("LIESMICH.txt").decode()


# --- LIESMICH sagt nichts, was im Archiv nicht steht ---------------------------------------------


async def test_the_readme_only_names_withheld_columns_whose_file_exists(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """`invites` ist geteilt und hat keine personenbezogene Spalte — im PERSÖNLICHEN Export gibt es
    also kein `data/invites.json`. Vorher stand `invites.code` trotzdem unter „Der Schlüssel bleibt
    sichtbar", und dieselbe Tabelle zwanzig Zeilen tiefer korrekt unter „nur im Haushalts-Export".
    Ein Text, der sich selbst widerspricht, ist schlimmer als einer, der schweigt."""
    ids = await _seed(pg)
    _as(app_client, ids, "member", "member")

    archive = _open((await app_client.get("/v1/me/export")).content)
    readme = archive.read("LIESMICH.txt").decode()
    names = set(archive.namelist())

    assert "data/invites.json" not in names
    assert "invites.code" not in readme
    # Gegenprobe: eine Spalte, deren Datei sehr wohl da ist, wird weiterhin genannt.
    assert "data/users.json" in names
    assert "users.password_hash" in readme


async def test_the_household_readme_names_invites_because_the_file_is_there(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    archive = _open((await app_client.get("/v1/household/export")).content)
    assert "data/invites.json" in archive.namelist()
    assert "invites.code" in archive.read("LIESMICH.txt").decode()


async def test_the_exclusion_heading_does_not_claim_they_lack_personal_data(
    app_client: AsyncClient, pg: PgDatabase
) -> None:
    """Die alte Überschrift „Ganze Tabellen ohne Personenbezug" war für fünf der elf Einträge
    falsch — `audit_log` trägt `actor_id`, `target_id` und `household_id`; Personenbezug ist ihr
    Zweck. Die Begründungen darunter waren richtig, nur die Überschrift behauptete etwas, das die
    Tabellen nicht hergeben."""
    ids = await _seed(pg)
    _as(app_client, ids, "admin", "admin")

    readme = (
        _open((await app_client.get("/v1/household/export")).content).read("LIESMICH.txt").decode()
    )

    assert "Ganze Tabellen ohne Personenbezug" not in readme
    assert "audit_log" in readme
