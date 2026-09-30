"""Retention reaper: hard-delete tombstoned fact rows once their ``deleted_at`` is older than the
retention window (ARCHITECTURE §9). Soft-delete (set ``deleted_at``) is sync-able and reversible
via the trash; this reaper is the *only* place rows leave the database for good.

Runs as ``custode_maint`` (spans households, like the sync/outbox reapers) on the daily cron. The
kernel must not know module table names (E2 — module boundaries), so the worker (composition root)
passes the table allow-list in. Names are validated against a strict identifier pattern before
interpolation, because table names cannot be bound as SQL parameters. Child rows tied via
``ON DELETE CASCADE`` (e.g. ``note_versions``, ``letter_reads``) are removed by the FK action,
which runs regardless of RLS or the caller's grants on the child table."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger

# Postgres unquoted identifier: lower snake_case. Anything else is rejected rather than escaped —
# the table list is code-defined (never user input), so a mismatch is a bug, not an attack.
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

_log = get_logger("retention")


@dataclass(frozen=True)
class RetentionResult:
    """How many tombstoned rows were purged, per table — and which tables refused.

    ``failed`` is not decoration: a reaper that silently skips a table looks exactly like a reaper
    with nothing to do. The caller alerts on it.
    """

    removed: dict[str, int]
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.removed.values())


def _purge_sql(table: str) -> Any:
    if not _IDENT.match(table):
        raise ValueError(f"unsafe retention table name: {table!r}")
    return text(
        f"DELETE FROM {table} "  # noqa: S608 — table validated against _IDENT, never user input
        "WHERE deleted_at IS NOT NULL AND deleted_at < now() - make_interval(days => :days)"
    )


async def reap_deleted(
    session: AsyncSession, *, retention_days: int, tables: tuple[str, ...]
) -> RetentionResult:
    """Delete tombstoned rows older than ``retention_days`` from each table in ``tables``.

    **One transaction per table, not one for the whole run.** The original shape — a single
    transaction — meant any failure took the entire purge with it, and that is exactly what
    happened: two tables joined the list in Phase 9 without the grants ``custode_maint`` needs, and
    because Postgres checks table privileges at *plan* time, the job died every night before
    touching anything (BUGLOG 2026-07-31). A partial purge is a delay; a total one is a broken
    promise to every user who emptied their trash.

    A failing table is logged and skipped, and its name lands in ``failed`` so the caller can alert
    on it. Returns per-table counts — no row contents, the caller logs aggregates only (no PII).
    """
    removed: dict[str, int] = {}
    failed: dict[str, str] = {}
    for table in tables:
        statement = _purge_sql(table)  # raises on a bad identifier before any DB work
        try:
            async with session.begin():
                result = cast(
                    CursorResult[Any], await session.execute(statement, {"days": retention_days})
                )
                removed[table] = result.rowcount
        except SQLAlchemyError as exc:
            await session.rollback()
            # The table name is code-defined, the exception class is ours to log; the message may
            # carry SQL but never a row value.
            removed[table] = 0
            failed[table] = type(exc).__name__
            _log.error("retention_table_failed", table=table, error=type(exc).__name__)
    return RetentionResult(removed=removed, failed=failed)
