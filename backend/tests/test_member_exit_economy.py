"""Der Ökonomie-Teil des Austritts (KONZEPT §5.1, 11-S1b) — Testcontainers PG 18.

Die zentrale Behauptung ist nicht „das Konto ist leer", sondern: **die Salden aller übrigen
Mitglieder sind unverändert.** Der Ledger ist eine doppelte Buchführung, Salden sind Summen und
nie gespeicherte Felder (ADR-0035). Wer die Zeilen einer Person löschte statt eine
Verfallsbuchung zu schreiben, veränderte damit die Salden anderer — ein Danke-Punkt
``member:A -> member:B`` gehört beiden Seiten — und könnte sie unter null drücken, was die
Invariante „keine negativen Salden, nirgends" bricht.

Zweite Behauptung, ebenso wichtig und leicht zu übersehen: **die Reihenfolge**. Verfiele der
Restsaldo vor dem Auflösen der Handelspositionen, käme das freigegebene Escrow danach an und läge
für immer auf einem Konto, das keine Route mehr auflöst.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    import os

    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = os.environ.get("CUSTODE_DATABASE_URL")
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    try:
        yield
    finally:
        if engine_mod._engine is not None:
            await engine_mod._engine.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        if prev is None:
            os.environ.pop("CUSTODE_DATABASE_URL", None)
        else:
            os.environ["CUSTODE_DATABASE_URL"] = prev
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
async def world(pg: PgDatabase, db: None) -> dict[str, uuid.UUID]:
    """Ein Haushalt, drei Mitglieder. Der Aussteiger hat Punkte, ein offenes Verkaufs-Listing
    (Escrow gebunden), einen angenommenen Kauf und eine zugewiesene Aufgabe."""
    ids = {
        "household": uuid.uuid4(),
        "leaver": uuid.uuid4(),
        "seller": uuid.uuid4(),
        "other": uuid.uuid4(),
        "task_own": uuid.uuid4(),
        "task_sold": uuid.uuid4(),
        "task_bought": uuid.uuid4(),
        "listing_open": uuid.uuid4(),
        "listing_bought": uuid.uuid4(),
    }
    conn = await _su(pg)
    try:
        await conn.execute("TRUNCATE households, users, memberships CASCADE;")
        await conn.execute(
            "TRUNCATE points_ledger, market_listings, task_instances, task_templates CASCADE;"
        )
        await conn.execute(
            "INSERT INTO households (id, name) VALUES ($1,'Haus');", ids["household"]
        )
        for key in ("leaver", "seller", "other"):
            await conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES ($1,$2,$3);",
                ids[key],
                f"{key}@example.org",
                key,
            )
            await conn.execute(
                "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,'member');",
                ids["household"],
                ids[key],
            )

        async def mint(to_account: str, amount: int, ref: str = "task_completion") -> None:
            await conn.execute(
                "INSERT INTO points_ledger "
                "(household_id, from_account, to_account, amount, ref_type) "
                "VALUES ($1,'system',$2,$3,$4);",
                ids["household"],
                to_account,
                amount,
                ref,
            )

        await mint(f"member:{ids['leaver']}", 100)
        await mint(f"member:{ids['seller']}", 40)
        await mint(f"member:{ids['other']}", 25)
        # Der entscheidende Datensatz: ein Danke-Punkt VOM AUSSTEIGER an ein bleibendes Mitglied.
        # Genau diese Zeile gehört beiden Seiten. Würde der Austritt die Zeilen der Person löschen
        # statt eine Verfallsbuchung zu schreiben, sänke der Saldo von `other` um 5 — ohne dass
        # `other` irgendetwas getan hätte. Ein Danke-Punkt zwischen zwei Bleibenden würde das
        # nicht zeigen, weil ein Löschen ihn gar nicht berührte.
        await conn.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type) "
            "VALUES ($1,$2,$3,5,'thanks');",
            ids["household"],
            f"member:{ids['leaver']}",
            f"member:{ids['other']}",
        )

        # Drei Aufgaben-Instanzen.
        for key, assignee in (
            ("task_own", ids["leaver"]),
            ("task_sold", ids["leaver"]),
            ("task_bought", ids["leaver"]),
        ):
            await conn.execute(
                "INSERT INTO task_instances (id, household_id, title, points, assigned_to, status) "
                "VALUES ($1,$2,$3,10,$4,'open');",
                ids[key],
                ids["household"],
                key,
                assignee,
            )

        # Offener Verkauf des Aussteigers: 30 Punkte liegen im Escrow.
        await conn.execute(
            "INSERT INTO market_listings "
            "(id, household_id, task_instance_id, title, seller_id, price, status) "
            "VALUES ($1,$2,$3,'Verkauf',$4,30,'open');",
            ids["listing_open"],
            ids["household"],
            ids["task_sold"],
            ids["leaver"],
        )
        await conn.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type, ref_id) "
            "VALUES ($1,$2,$3,30,'market_escrow',$4);",
            ids["household"],
            f"member:{ids['leaver']}",
            f"escrow:{ids['listing_open']}",
            ids["listing_open"],
        )

        # Angenommener Kauf des Aussteigers: der andere hat verkauft, 20 im Escrow.
        await conn.execute(
            "INSERT INTO market_listings "
            "(id, household_id, task_instance_id, title, seller_id, price, status, buyer_id) "
            "VALUES ($1,$2,$3,'Kauf',$4,20,'accepted',$5);",
            ids["listing_bought"],
            ids["household"],
            ids["task_bought"],
            ids["seller"],
            ids["leaver"],
        )
        await conn.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type, ref_id) "
            "VALUES ($1,$2,$3,20,'market_escrow',$4);",
            ids["household"],
            f"member:{ids['seller']}",
            f"escrow:{ids['listing_bought']}",
            ids["listing_bought"],
        )
    finally:
        await conn.close()
    return ids


async def _balance(pg: PgDatabase, account: str) -> int:
    conn = await _su(pg)
    try:
        credited = await conn.fetchval(
            "SELECT coalesce(sum(amount),0) FROM points_ledger WHERE to_account = $1;", account
        )
        debited = await conn.fetchval(
            "SELECT coalesce(sum(amount),0) FROM points_ledger WHERE from_account = $1;", account
        )
    finally:
        await conn.close()
    return int(credited) - int(debited)


async def _settle(ids: dict[str, uuid.UUID]) -> object:
    from app.member_exit import settle_member_exit

    return await settle_member_exit(household_id=ids["household"], member_id=ids["leaver"])


# --- die Invariante ------------------------------------------------------------------------------


async def test_other_members_balances_are_untouched(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der Kern. Der Verkäufer bekommt sein Escrow zurück (+20), sonst ändert sich für die
    Bleibenden nichts — insbesondere überlebt der Danke-Punkt zwischen ihnen."""
    before_other = await _balance(pg, f"member:{world['other']}")
    before_seller = await _balance(pg, f"member:{world['seller']}")

    await _settle(world)

    assert await _balance(pg, f"member:{world['other']}") == before_other
    # Der zurückgegebene Escrow des rückabgewickelten Kaufs.
    assert await _balance(pg, f"member:{world['seller']}") == before_seller + 20


async def test_no_account_goes_negative(world: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    """„Keine negativen Salden, nirgends" (KONZEPT §5.9) — auch nicht als Nebenwirkung."""
    await _settle(world)

    conn = await _su(pg)
    try:
        accounts = {
            r["a"]
            for r in await conn.fetch(
                "SELECT from_account AS a FROM points_ledger "
                "UNION SELECT to_account AS a FROM points_ledger;"
            )
        }
    finally:
        await conn.close()

    for account in accounts:
        if account == "system":
            continue  # die Quelle/Senke darf negativ sein, sie IST die Gegenbuchung
        assert await _balance(pg, account) >= 0, f"{account} ist negativ"


async def test_the_leavers_account_ends_at_zero(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """100 Startpunkte, minus 30 im Escrow, minus 5 verschenkt → 65 frei. Der Rückzug bringt die 30
    zurück, dann verfallen 95. Entscheidend ist die REIHENFOLGE: verfiele der Saldo zuerst, lägen
    die 30 danach für immer auf einem Konto ohne Person."""
    assert await _balance(pg, f"member:{world['leaver']}") == 65

    result = await _settle(world)

    assert await _balance(pg, f"member:{world['leaver']}") == 0
    assert result.points_expired == 95  # type: ignore[attr-defined]


async def test_the_expiry_is_a_booking_not_a_deletion(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Die Historie bleibt vollständig — der Ledger ist append-only, und der Verfall ist eine
    Zeile mit dem im KONZEPT wörtlich festgelegten ``ref_type``."""
    conn = await _su(pg)
    try:
        before = await conn.fetchval("SELECT count(*) FROM points_ledger;")
    finally:
        await conn.close()

    await _settle(world)

    conn = await _su(pg)
    try:
        after = await conn.fetchval("SELECT count(*) FROM points_ledger;")
        exits = await conn.fetchval(
            "SELECT count(*) FROM points_ledger WHERE ref_type = 'member_exit';"
        )
    finally:
        await conn.close()

    assert after > before, "es wurde gebucht, nicht gelöscht"
    assert exits == 1


# --- Handelspositionen ---------------------------------------------------------------------------


async def test_open_sale_is_withdrawn_and_accepted_purchase_reverted(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    result = await _settle(world)

    conn = await _su(pg)
    try:
        rows = {
            r["id"]: r["status"]
            for r in await conn.fetch("SELECT id, status FROM market_listings;")
        }
    finally:
        await conn.close()

    assert rows[world["listing_open"]] == "withdrawn"
    assert rows[world["listing_bought"]] == "reverted"
    assert result.withdrawn == 1 and result.reverted == 1  # type: ignore[attr-defined]


async def test_the_reverted_task_goes_back_to_its_seller(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Rückabwicklung heißt: die Aufgabe ist wieder die des Verkäufers, nicht herrenlos."""
    await _settle(world)

    conn = await _su(pg)
    try:
        assignee = await conn.fetchval(
            "SELECT assigned_to FROM task_instances WHERE id = $1;", world["task_bought"]
        )
    finally:
        await conn.close()
    assert assignee == world["seller"]


async def test_remaining_assignments_return_to_the_pool(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """``assigned_to`` hat keinen Fremdschlüssel — bliebe die ID stehen, sähe die Aufgabe für alle
    anderen aus wie „vergeben", tauchte aber in keiner Liste mehr auf."""
    await _settle(world)

    conn = await _su(pg)
    try:
        assignee = await conn.fetchval(
            "SELECT assigned_to FROM task_instances WHERE id = $1;", world["task_own"]
        )
    finally:
        await conn.close()
    assert assignee is None


# --- Idempotenz ----------------------------------------------------------------------------------


async def test_running_twice_books_nothing_extra(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Outbox-Zustellung ist at-least-once. Ein zweiter Lauf darf keine zweite Verfallsbuchung
    erzeugen — sonst entstünde ein negativer Saldo aus dem Nichts."""
    await _settle(world)
    conn = await _su(pg)
    try:
        after_first = await conn.fetchval("SELECT count(*) FROM points_ledger;")
    finally:
        await conn.close()

    second = await _settle(world)

    conn = await _su(pg)
    try:
        after_second = await conn.fetchval("SELECT count(*) FROM points_ledger;")
    finally:
        await conn.close()

    assert after_second == after_first
    assert second.points_expired == 0  # type: ignore[attr-defined]
    assert await _balance(pg, f"member:{world['leaver']}") == 0


# --- Der Kauf, der schon erledigt war (BUGLOG 2026-08-03) ----------------------------------------


async def _mark_bought_task_done(pg: PgDatabase, world: dict[str, uuid.UUID]) -> None:
    """Der Käufer hat geliefert, aber niemand hat abgerechnet.

    Es gibt kein Auto-Settle: ``settle_listing`` hat genau einen Aufrufer, den Knopf „Auszahlen"
    im Web. Der Zustand ist damit kein Randfall, sondern der Normalfall zwischen zwei Klicks —
    ``test_marketplace_http.test_full_escrow_lifecycle`` durchläuft ihn selbst.
    """
    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE task_instances SET status='done' WHERE id = $1;", world["task_bought"]
        )
    finally:
        await conn.close()


async def test_exit_survives_a_bought_task_that_is_already_done(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der Austritt darf daran nicht scheitern — und tat es.

    ``release_positions_of`` wickelte jeden angenommenen Kauf über ``revert_listing`` zurück, und
    das ruft ``tasks.api.reassign_instance``, das eine nicht mehr offene Instanz mit 409 ablehnt.
    Der Handler starb, fünf Zustellversuche, DLQ — und weil alle drei Schritte des Austritts
    **eine Transaktion** teilen, lief danach *nichts*: kein Escrow frei, keine Aufgabe zurück,
    kein Punkte-Verfall. Die Person war draußen, ihre Ökonomie blieb liegen.
    """
    await _mark_bought_task_done(pg, world)

    settlement = await _settle(world)

    assert settlement.reverted == 1  # type: ignore[attr-defined]
    assert await _balance(pg, f"member:{world['leaver']}") == 0


async def test_a_delivered_task_pays_the_buyer_not_the_seller(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Wer geliefert hat, hat verdient — auch wenn er geht.

    Die naheliegende Rettung wäre, den Escrow einfach an den Verkäufer zurückzugeben. Das wäre
    falsch: der Verkäufer hat die Arbeit *bekommen*. Er bekäme die erledigte Aufgabe **und** seine
    Punkte zurück, und der Käufer ginge leer aus. KONZEPT §5.10 zahlt bei Erledigung an den Käufer;
    dass dieser gerade austritt, ändert daran nichts — sein Saldo verfällt danach ohnehin als
    eigene Buchung (Schritt 3, deshalb steht er zuletzt).
    """
    before_seller = await _balance(pg, f"member:{world['seller']}")
    await _mark_bought_task_done(pg, world)

    await _settle(world)

    conn = await _su(pg)
    try:
        status = await conn.fetchval(
            "SELECT status FROM market_listings WHERE id = $1;", world["listing_bought"]
        )
        assignee = await conn.fetchval(
            "SELECT assigned_to FROM task_instances WHERE id = $1;", world["task_bought"]
        )
        settle_rows = await conn.fetchval(
            "SELECT count(*) FROM points_ledger WHERE ref_type='market_settle' AND ref_id=$1;",
            world["listing_bought"],
        )
    finally:
        await conn.close()

    assert status == "settled"
    assert settle_rows == 1
    # Der Verkäufer bekommt sein Escrow NICHT zurück — er hat die Arbeit erhalten.
    assert await _balance(pg, f"member:{world['seller']}") == before_seller
    # Die erledigte Aufgabe wird nicht zurückgereicht; sie ist erledigt.
    assert assignee == world["leaver"]


async def test_exit_survives_a_bought_task_that_was_deleted(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Zweiter Pfad derselben Klasse: ist die Instanz getombstonet, wirft ``get_instance`` 404
    statt 409 — mit demselben Ausgang. Niemand hat die Arbeit gemacht, also geht das Escrow an den
    Verkäufer zurück; zurückzugeben ist nichts."""
    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE task_instances SET deleted_at = now() WHERE id = $1;", world["task_bought"]
        )
    finally:
        await conn.close()

    before_seller = await _balance(pg, f"member:{world['seller']}")
    settlement = await _settle(world)

    assert settlement.reverted == 1  # type: ignore[attr-defined]
    assert await _balance(pg, f"member:{world['seller']}") == before_seller + 20
