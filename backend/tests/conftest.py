from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from dbfixture import INFRA_SKIP_PREFIX, PgCluster, PgDatabase, start_cluster

__all__ = ["PgDatabase"]


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- Postgres: one cluster per session, one database per module ------------------------------


@pytest.fixture(scope="session")
def pg_cluster() -> Iterator[PgCluster]:
    """The single Postgres container of the run (see ``dbfixture`` for why it is single)."""
    try:
        yield from start_cluster()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def pg(pg_cluster: PgCluster) -> Iterator[PgDatabase]:
    """A fresh, fully migrated database for this test module.

    Copied from the template rather than migrated — the 72 migrations run once per session, not
    once per module. The handle is interface-compatible with the ``PostgresContainer`` these
    fixtures used to yield.
    """
    database = pg_cluster.create_database()
    try:
        yield database
    finally:
        pg_cluster.drop_database(database)


@pytest.fixture(scope="module")
def migrated_pg(pg: PgDatabase) -> PgDatabase:
    """Alias for :func:`pg`. Both names grew in parallel across the suite; keeping the alias keeps
    the switch to the shared cluster a one-line change per module."""
    return pg


# --- Redis ------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_server() -> Iterator[Any]:
    """A throwaway Redis (generic Testcontainer, no extra needed)."""
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    try:
        container = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
        container.start()
    except Exception as exc:  # Docker not available
        pytest.skip(f"{INFRA_SKIP_PREFIX} Redis container did not start: {exc}")
    try:
        wait_for_logs(container, "Ready to accept connections")
        yield container
    finally:
        container.stop()


@pytest.fixture
async def redis_db(redis_server: Any) -> AsyncIterator[None]:
    """Repoint the global Redis client at the container and flush it for a clean slate."""
    import app.kernel.redis as redis_mod
    from app.settings import get_settings

    host = redis_server.get_container_host_ip()
    port = redis_server.get_exposed_port(6379)
    prev = os.environ.get("CUSTODE_REDIS_URL")
    os.environ["CUSTODE_REDIS_URL"] = f"redis://{host}:{port}/0"
    get_settings.cache_clear()
    await redis_mod.close_redis()
    await redis_mod.get_redis().flushdb()
    try:
        yield
    finally:
        await redis_mod.close_redis()
        if prev is None:
            os.environ.pop("CUSTODE_REDIS_URL", None)
        else:
            os.environ["CUSTODE_REDIS_URL"] = prev
        get_settings.cache_clear()


@pytest.fixture
def captured_logs() -> Iterator[list[dict[str, object]]]:
    """Capture structlog events for assertions about what we do NOT log.

    Several modules promise "never a token / never a URL / never PII in the logs". Until now that
    was only a docstring — a claim nothing checked (BUGLOG 2026-07-30). ``capture_logs`` swaps in
    a capturing processor chain for the duration of the test, so a promise can actually fail."""
    from structlog.testing import capture_logs as _capture

    with _capture() as entries:
        yield entries


# --- The gate: a run that skipped its infrastructure is red, not green ------------------------

# Anything that means "the environment could not provide what the test needs" — as opposed to a
# test that skipped itself on purpose. The prefix is set by our own fixtures; the two patterns
# after it cover the Radicale suites, which bring their own container.
_INFRA_SKIP = re.compile(
    rf"{re.escape(INFRA_SKIP_PREFIX)}|Docker/\w+ not available|container did not become ready"
)
_OPT_OUT = "CUSTODE_TESTS_ALLOW_SKIPPED_INFRA"

_infra_skips: list[str] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not report.skipped:
        return
    reason = ""
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
    else:
        reason = str(longrepr)
    if _INFRA_SKIP.search(reason):
        _infra_skips.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run when tests were skipped because the infrastructure was missing.

    Without this, ``pytest`` exits 0 after skipping every database-backed test — 563 of 937 on
    2026-08-03 — and CI reports a green build for a run that proved nothing. That is the same
    failure shape as the retention reaper that died silently for three weeks (BUGLOG 2026-07-31),
    only on the level of the suite.

    Opting out is possible and deliberate (``CUSTODE_TESTS_ALLOW_SKIPPED_INFRA=1``) — for a quick
    pure-unit loop without Docker. It must be a decision, not the default: a default that hides
    missing coverage is how the coverage went missing.
    """
    if not _infra_skips or os.environ.get(_OPT_OUT):
        return
    writer = session.config.pluginmanager.get_plugin("terminalreporter")
    message = (
        f"{len(_infra_skips)} test(s) were skipped because Docker/Postgres/Redis/Radicale were "
        f"unavailable — this run proved nothing about RLS, HTTP or export behaviour.\n"
        f"First: {_infra_skips[0]}\n"
        f"Start Docker, or set {_OPT_OUT}=1 to accept the gap knowingly."
    )
    if writer is not None:
        writer.write_sep("=", "infrastructure missing", red=True, bold=True)
        writer.write_line(message)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
