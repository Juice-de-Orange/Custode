"""One Postgres cluster per test session, one database per test module.

**Why this exists.** Until 2026-08-03 each of the 75 Postgres-backed test modules started its own
``PostgresContainer`` and ran all 72 migrations into it. Two costs, and the second one is the
serious one:

* 6:52 of the 7:19 backend CI runtime went into container starts and migrations, and *every new
  migration multiplied by 75* — the schedule got worse with every slice.
* Each of those fixtures caught **every** exception as "Docker not available" and called
  ``pytest.skip``. Without Docker the suite reported ``563 skipped, 374 passed`` and exited 0:
  the complete RLS, HTTP and export coverage vanished and the job went green. That is the third
  proof rule of this codebase ("a job that only logs when it acts is silent when it fails") one
  level up — on the suite itself. The counter-measure lives in ``conftest.pytest_sessionfinish``.

**The shape now.** One container per session; the four DB roles created once (roles are
cluster-wide in Postgres, so once is enough); the migrations applied once into a **template**
database; and every test module gets its own database via ``CREATE DATABASE … TEMPLATE``, which is
a file copy — milliseconds instead of seconds. Isolation between modules is unchanged: a separate
database is at least as strong a boundary as a separate container was.

**A side effect that makes the fixture more honest, not less.** All four roles exist from the
start. The migrations grant to ``ops_readonly``/``ops_actions`` only ``IF EXISTS`` (see 0056-0059,
0064), so a container that knew only ``custode_app`` silently skipped those grants - the template
is closer to production than the old per-file setup was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[1]

#: Name and password of every DB role the suite connects as. The passwords match the ones the
#: per-file fixtures used, because the test modules build their own connection strings from them.
ROLES: tuple[tuple[str, str], ...] = (
    ("custode_app", "app"),
    ("custode_maint", "maint"),
    ("ops_readonly", "ops"),
    ("ops_actions", "ops_act"),
)

_TEMPLATE_DB = "custode_template"

#: Marker in the skip reason. ``conftest`` matches on it to turn "infrastructure missing" into a
#: red run instead of a green one; a plain string would drift the moment somebody rewords it.
INFRA_SKIP_PREFIX = "custode-infra-unavailable:"


@dataclass(frozen=True)
class PgDatabase:
    """A per-module database inside the shared cluster.

    Deliberately quacks like ``PostgresContainer``: the test modules build their own DSNs from
    exactly these five members (``username``/``password``/``dbname`` plus
    ``get_container_host_ip``/``get_exposed_port``), so moving a module onto the shared cluster
    costs one type annotation and nothing else.

    ``username``/``password`` are the cluster **superuser** — same as before, where they were the
    container's own credentials. The unprivileged roles are in :data:`ROLES`.
    """

    host: str
    port: int
    username: str
    password: str
    dbname: str

    def get_container_host_ip(self) -> str:
        return self.host

    def get_exposed_port(self, port: int = 5432) -> int:
        return self.port

    def dsn(self, user: str, password: str) -> str:
        """SQLAlchemy/asyncpg URL for one of the roles against *this* module's database."""
        return f"postgresql+asyncpg://{user}:{password}@{self.host}:{self.port}/{self.dbname}"


class PgCluster:
    """The session-wide container plus the migrated template database."""

    def __init__(self, container: Any) -> None:
        self._container = container
        self.host: str = container.get_container_host_ip()
        self.port: int = int(container.get_exposed_port(5432))
        self.username: str = container.username
        self.password: str = container.password
        self.maintenance_db: str = container.dbname
        self._counter = 0

    # -- connection helpers -------------------------------------------------

    async def _connect(self, database: str) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            database=database,
        )

    async def _run(self, database: str, *statements: str) -> None:
        conn = await self._connect(database)
        try:
            for statement in statements:
                await conn.execute(statement)
        finally:
            await conn.close()

    async def _run_with_args(self, database: str, statement: str, *args: object) -> None:
        conn = await self._connect(database)
        try:
            await conn.execute(statement, *args)
        finally:
            await conn.close()

    # -- one-time setup -----------------------------------------------------

    def provision(self) -> None:
        """Create the roles and migrate the template database. Called once per session."""
        asyncio.run(self._provision_roles())
        asyncio.run(self._create_template())
        self._migrate_template()
        # Alembic's engine is disposed by ``migrations/env.py``, but a lingering backend would
        # make every ``CREATE DATABASE … TEMPLATE`` fail with 55006. Terminate defensively: the
        # error would otherwise surface as a confusing failure in an unrelated test module.
        asyncio.run(self._disconnect_template())

    async def _provision_roles(self) -> None:
        grantees = ", ".join(name for name, _ in ROLES)
        statements = [
            f"CREATE ROLE {name} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS;"
            for name, password in ROLES
        ]
        statements.append(f"GRANT USAGE ON SCHEMA public TO {grantees};")
        await self._run(self.maintenance_db, *statements)

    async def _create_template(self) -> None:
        await self._run(self.maintenance_db, f'CREATE DATABASE "{_TEMPLATE_DB}";')
        # The roles need USAGE in the template too — ``GRANT … ON SCHEMA public`` is per database,
        # and the template is what every module database is copied from.
        grantees = ", ".join(name for name, _ in ROLES)
        await self._run(_TEMPLATE_DB, f"GRANT USAGE ON SCHEMA public TO {grantees};")

    def _migrate_template(self) -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.set_main_option(
            "sqlalchemy.url",
            f"postgresql+asyncpg://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{_TEMPLATE_DB}",
        )
        command.upgrade(cfg, "head")

    async def _disconnect_template(self) -> None:
        # Bound parameter, not an f-string: the database name is a constant here, but a query
        # built by concatenation is the shape S608 exists to catch, and a test helper is not the
        # place to teach the exception.
        await self._run_with_args(
            self.maintenance_db,
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid();",
            _TEMPLATE_DB,
        )

    # -- per-module databases ----------------------------------------------

    def create_database(self) -> PgDatabase:
        self._counter += 1
        name = f"custode_t{self._counter:03d}"
        asyncio.run(
            self._run(self.maintenance_db, f'CREATE DATABASE "{name}" TEMPLATE "{_TEMPLATE_DB}";')
        )
        return PgDatabase(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            dbname=name,
        )

    def drop_database(self, database: PgDatabase) -> None:
        # WITH (FORCE) so a leaked connection from a failing test cannot wedge the teardown; the
        # database is throwaway either way.
        asyncio.run(
            self._run(
                self.maintenance_db, f'DROP DATABASE IF EXISTS "{database.dbname}" WITH (FORCE);'
            )
        )

    def stop(self) -> None:
        self._container.stop()


def start_cluster() -> Iterator[PgCluster]:
    """Start the container, provision it, yield it, stop it.

    Raises ``RuntimeError`` when the container cannot be started or provisioned — the caller turns
    that into a *marked* skip so the session-finish gate can tell "no Docker" apart from a test
    that skipped itself on purpose.
    """
    from testcontainers.postgres import PostgresContainer

    try:
        container = PostgresContainer("postgres:18")
        container.start()
    except Exception as exc:  # Docker not available
        raise RuntimeError(f"{INFRA_SKIP_PREFIX} Postgres container did not start: {exc}") from exc

    cluster = PgCluster(container)
    try:
        cluster.provision()
    except Exception as exc:
        container.stop()
        raise RuntimeError(f"{INFRA_SKIP_PREFIX} Postgres provisioning failed: {exc}") from exc

    try:
        yield cluster
    finally:
        cluster.stop()
