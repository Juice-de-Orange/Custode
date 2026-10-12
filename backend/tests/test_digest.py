"""Weekly-digest fan-out test (Testcontainers PG 18, Roadmap Phase 8). Under the maint role the
digest reaches adult members of opted-in households, skips opt-outs, and excludes children + members
without an e-mail. Graceful Enhancement: it also runs cleanly through the Null mail adapter. Skipped
without Docker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.null import NullMail
from app.modules.digest.service import send_weekly_digests
from conftest import PgDatabase

_NOW = datetime(2026, 6, 29, 7, 0, tzinfo=UTC)


class FakeMail:
    """Captures every (to, subject, body) the digest sends; always accepts."""

    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, to: str, subject: str, body_md: str) -> bool:
        self.sent.append((to, subject, body_md))
        return True


async def _seed(container: PgDatabase, hh_a: uuid.UUID, hh_b: uuid.UUID) -> None:
    su = await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=container.username,
        password=container.password,
        database=container.dbname,
    )
    try:
        # The digest spans the whole DB, so isolate this test from the shared module-scoped
        # container by clearing the tables it reads first.
        await su.execute("TRUNCATE households, users, memberships, task_instances CASCADE;")
        admin_a, child_a, member_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        # Household A is opted-in (default); B has opted out via settings_json.
        await su.execute(
            "INSERT INTO households (id, name, settings_json) VALUES "
            "($1,'Familie A','{}'::jsonb), ($2,'WG B','{\"digest_enabled\": false}'::jsonb);",
            hh_a,
            hh_b,
        )
        await su.execute(
            "INSERT INTO users (id, display_name, email) VALUES "
            "($1,'Admin A','a@example.de'), ($2,'Kind A', NULL), ($3,'Member B','b@example.de');",
            admin_a,
            child_a,
            member_b,
        )
        await su.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES "
            "($1,$2,'admin'), ($1,$3,'child'), ($4,$5,'member');",
            hh_a,
            admin_a,
            child_a,
            hh_b,
            member_b,
        )
        # Household A: two open tasks, one of them overdue; B: one open task (but B opted out).
        await su.execute(
            "INSERT INTO task_instances (household_id, title, status, due_at) VALUES "
            "($1,'overdue','open',$2), ($1,'soon','open',$3), ($4,'b-task','open',$3);",
            hh_a,
            _NOW - timedelta(days=2),
            _NOW + timedelta(days=2),
            hh_b,
        )
    finally:
        await su.close()


def _maint_sessionmaker(container: PgDatabase) -> async_sessionmaker[AsyncSession]:
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(5432))
    engine = create_async_engine(
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{container.dbname}"
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_digest_reaches_optedin_adults_only(migrated_pg: PgDatabase) -> None:
    hh_a, hh_b = uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, hh_a, hh_b)

    mail = FakeMail()
    maker = _maint_sessionmaker(migrated_pg)
    async with maker() as session:
        sent = await send_weekly_digests(session, mail=mail, brand="Custode", now=_NOW)

    # Only Household A's adult with an e-mail is reached (child + opted-out WG B excluded).
    assert sent == 1
    assert [to for (to, _s, _b) in mail.sent] == ["a@example.de"]
    _to, subject, body = mail.sent[0]
    assert "Familie A" in subject
    assert "Offene Aufgaben: 2 (davon 1 überfällig)" in body


async def test_digest_runs_through_null_mail(migrated_pg: PgDatabase) -> None:
    hh_a, hh_b = uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, hh_a, hh_b)

    # Graceful base path: the Null adapter accepts but transmits nothing — no error, same selection.
    maker = _maint_sessionmaker(migrated_pg)
    async with maker() as session:
        sent = await send_weekly_digests(session, mail=NullMail(), brand="Custode", now=_NOW)
    assert sent == 1


async def test_digest_speaks_each_recipients_language(migrated_pg: PgDatabase) -> None:
    """Each adult gets the digest in their own ``users.locale``; anything but German is English."""
    hh_a, hh_b = uuid.uuid4(), uuid.uuid4()
    await _seed(migrated_pg, hh_a, hh_b)
    su = await asyncpg.connect(
        host=migrated_pg.get_container_host_ip(),
        port=int(migrated_pg.get_exposed_port(5432)),
        user=migrated_pg.username,
        password=migrated_pg.password,
        database=migrated_pg.dbname,
    )
    try:
        await su.execute("UPDATE users SET locale = 'en' WHERE email = 'a@example.de';")
        second, third = uuid.uuid4(), uuid.uuid4()
        await su.execute(
            "INSERT INTO users (id, display_name, email, locale) VALUES "
            "($1,'Member A2','a2@example.de','de-AT'), ($2,'Member A3','a3@example.de','fr');",
            second,
            third,
        )
        await su.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES "
            "($1,$2,'member'), ($1,$3,'member');",
            hh_a,
            second,
            third,
        )
    finally:
        await su.close()

    mail = FakeMail()
    maker = _maint_sessionmaker(migrated_pg)
    async with maker() as session:
        sent = await send_weekly_digests(session, mail=mail, brand="Custode", now=_NOW)

    assert sent == 3
    by_to = {to: (subject, body) for (to, subject, body) in mail.sent}
    en_subject, en_body = by_to["a@example.de"]
    assert en_subject == "Custode: weekly overview for Familie A"
    assert "Open tasks: 2 (1 overdue)." in en_body
    de_subject, de_body = by_to["a2@example.de"]
    assert de_subject == "Custode: Wochenüberblick für Familie A"
    assert "Offene Aufgaben: 2 (davon 1 überfällig)." in de_body
    assert by_to["a3@example.de"] == (en_subject, en_body)  # no French templates -> English
