"""``demo-reset`` — put the public demo back to its seed (docs/demo.md).

``python -m app.scripts.demo_reset [--lang en] [--loop]``

**How.** The first run on an empty, migrated database copies every table of ``public`` into the
schema ``demo_base`` — the state right after the migrations, reference data included (the
ingredient tables are filled by migrations, so "truncate everything" would lose them) — and
then seeds the demo household. Every later run restores that copy in **one transaction**
(``TRUNCATE`` all tables, ``INSERT … SELECT`` from ``demo_base``, foreign-key triggers off for
the copy) and seeds again. Seeding fresh instead of restoring a seeded snapshot is deliberate:
the seed's dates are relative to *today* (this week's meal plan, tasks due today), and a
snapshot from launch day would show a stale week a month later.

**Safety.** It destroys every row in the database, so it refuses to run unless
``CUSTODE_DEMO_MODE=on``, and it needs the owner URL (``CUSTODE_DATABASE_URL_ADMIN``) because the
app roles may not truncate. The base copy remembers the Alembic revision it was taken at; after
an upgrade with new migrations it refuses instead of restoring old table shapes — a demo is
reset by recreating its volumes (docs/demo.md, "Update").

``--loop`` runs once at start, then at every full hour — the ``demo-reset`` container of
``docker-compose.demo.yml``. While a reset runs, ``/v1/demo`` reports ``resetting`` (Redis flag).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.demo import RESETTING_KEY
from app.kernel.redis import get_redis
from app.logging import configure_logging, get_logger
from app.scripts.seed_demo import CONTENT, seed_demo_admin
from app.settings import get_settings

BASE_SCHEMA = "demo_base"
# Any constant works; it only has to be the same for every concurrent reset.
_LOCK_ID = 0x6375_7374_6465_6D6F  # "custdemo"


@dataclass(frozen=True)
class ResetResult:
    action: str  # "initialised" | "restored"
    seconds: float
    rows: dict[str, int]  # non-empty tables after the seed


def _q(name: str) -> str:
    """Quote an identifier. The names come from ``pg_catalog``, never from input — quoting keeps a
    table that needs it (none today) from turning into SQL."""
    return '"' + name.replace('"', '""') + '"'


async def _tables(conn: AsyncConnection) -> list[str]:
    """Every ordinary table in ``public`` (partitions included, as leaves) except Alembic's."""
    rows = await conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version' "
            "ORDER BY c.relname"
        )
    )
    return [r[0] for r in rows]


async def _columns(conn: AsyncConnection, table: str) -> list[str]:
    """Insertable columns: generated columns are computed again on insert."""
    rows = await conn.execute(
        text(
            "SELECT a.attname FROM pg_attribute a "
            "WHERE a.attrelid = CAST(:t AS regclass) AND a.attnum > 0 "
            "AND NOT a.attisdropped AND a.attgenerated = '' ORDER BY a.attnum"
        ),
        {"t": f"public.{_q(table)}"},
    )
    return [r[0] for r in rows]


async def _revision(conn: AsyncConnection) -> str:
    return str(await conn.scalar(text("SELECT version_num FROM alembic_version")))


async def _base_revision(conn: AsyncConnection) -> str | None:
    """The revision the base copy was taken at (stored as the schema comment), None if absent."""
    exists = await conn.scalar(
        text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": BASE_SCHEMA}
    )
    if not exists:
        return None
    comment = await conn.scalar(
        text("SELECT obj_description(CAST(:s AS regnamespace), 'pg_namespace')"),
        {"s": BASE_SCHEMA},
    )
    return str(comment) if comment else ""


async def _take_base(conn: AsyncConnection, tables: list[str], revision: str) -> None:
    await conn.execute(text(f"CREATE SCHEMA {BASE_SCHEMA}"))
    for table in tables:
        cols = ", ".join(_q(c) for c in await _columns(conn, table))
        await conn.execute(
            text(
                f"CREATE TABLE {BASE_SCHEMA}.{_q(table)} AS "  # noqa: S608 - catalog identifiers
                f"SELECT {cols} FROM public.{_q(table)}"
            )
        )
    await conn.execute(text(f"COMMENT ON SCHEMA {BASE_SCHEMA} IS '{revision}'"))


async def _restore_base(conn: AsyncConnection, tables: list[str]) -> None:
    # Replica role: no triggers, no FK checks while the copy goes back in — the copy is a
    # consistent state as a whole, row order within it is not.
    await conn.execute(text("SET LOCAL session_replication_role = replica"))
    await conn.execute(text("TRUNCATE " + ", ".join(f"public.{_q(t)}" for t in tables)))
    for table in tables:
        cols = ", ".join(_q(c) for c in await _columns(conn, table))
        await conn.execute(
            text(
                f"INSERT INTO public.{_q(table)} ({cols}) OVERRIDING SYSTEM VALUE "  # noqa: S608
                f"SELECT {cols} FROM {BASE_SCHEMA}.{_q(table)}"
            )
        )


async def table_counts(conn: AsyncConnection) -> dict[str, int]:
    """Row count of every non-empty table in ``public`` (the before/after evidence)."""
    counts: dict[str, int] = {}
    for table in await _tables(conn):
        n = int(await conn.scalar(text(f"SELECT count(*) FROM public.{_q(table)}")) or 0)  # noqa: S608
        if n:
            counts[table] = n
    return counts


async def reset_demo(lang: str = "en") -> ResetResult:
    settings = get_settings()
    if not settings.demo_mode:
        raise SystemExit("demo-reset deletes every row; it runs only with CUSTODE_DEMO_MODE=on.")
    if not settings.database_url_admin:
        raise SystemExit("demo-reset needs CUSTODE_DATABASE_URL_ADMIN (the owner role).")

    started = time.monotonic()
    redis = get_redis()
    await redis.set(RESETTING_KEY, "1", ex=300)
    engine = create_async_engine(settings.database_url_admin)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
            tables = await _tables(conn)
            revision = await _revision(conn)
            base = await _base_revision(conn)
            if base is None:
                users = int(await conn.scalar(text("SELECT count(*) FROM public.users")) or 0)
                if users:
                    raise SystemExit(
                        "demo-reset: the database has accounts but no base copy. Start the demo "
                        "on empty volumes (docs/demo.md)."
                    )
                await _take_base(conn, tables, revision)
                action = "initialised"
            elif base != revision:
                raise SystemExit(
                    f"demo-reset: the base copy is from revision {base}, the database is at "
                    f"{revision}. Recreate the demo's volumes after an update (docs/demo.md)."
                )
            else:
                await _restore_base(conn, tables)
                action = "restored"
        await seed_demo_admin(lang)
        async with engine.connect() as conn:
            rows = await table_counts(conn)
    finally:
        await engine.dispose()
        await redis.delete(RESETTING_KEY)
    result = ResetResult(action=action, seconds=round(time.monotonic() - started, 2), rows=rows)
    get_logger("demo").info(
        "demo_reset",
        action=result.action,
        seconds=result.seconds,
        tables=len(rows),
        rows=sum(rows.values()),
    )
    return result


def _seconds_to_next_hour(now: datetime) -> float:
    nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (nxt - now).total_seconds()


async def _loop(lang: str) -> None:
    log = get_logger("demo")
    while True:
        try:
            result = await reset_demo(lang)
            print(
                f"demo-reset: {result.action} in {result.seconds}s, "
                f"{sum(result.rows.values())} rows in {len(result.rows)} tables",
                flush=True,
            )
        except SystemExit:
            raise
        except Exception:  # keep the schedule alive; the next hour tries again
            log.exception("demo_reset_failed")
        await asyncio.sleep(_seconds_to_next_hour(datetime.now(UTC)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="demo-reset", description=__doc__.splitlines()[0])
    parser.add_argument("--lang", choices=sorted(CONTENT), default="en")
    parser.add_argument("--loop", action="store_true", help="reset now and at every full hour")
    args = parser.parse_args(argv)
    configure_logging(get_settings())
    if args.loop:
        asyncio.run(_loop(args.lang))
        return
    result = asyncio.run(reset_demo(args.lang))
    print(
        f"demo-reset: {result.action} in {result.seconds}s, "
        f"{sum(result.rows.values())} rows in {len(result.rows)} tables",
        flush=True,
    )


if __name__ == "__main__":
    main()
