"""Event dispatching (ARCHITECTURE §8.2).

Two implementations:

* :class:`InMemoryDispatcher` — synchronous in-process fan-out for tests and local
  wiring (no durability).
* :class:`OutboxDispatcher` — the durable worker path. It polls ``events_outbox``
  for due events (``FOR UPDATE SKIP LOCKED`` so concurrent workers never grab the
  same row), runs each registered handler **idempotently** (``processed_events``
  records ``(handler, event_id)``), retries with exponential backoff, and
  dead-letters to ``events_dlq`` after ``max_attempts``. It runs as ``custode_maint``
  and reads across households (RLS maint policy, migration 0004).

Handlers receive only the envelope and own their side effects (their own scoped
session). Delivery is at-least-once; a handler that already succeeded for an event
is skipped via the ledger, so handlers only need to tolerate re-delivery on the
rare crash between side effect and ledger write.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.envelope import EventEnvelope

EventHandler = Callable[[EventEnvelope], Awaitable[None]]

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_BACKOFF_S = 10.0


class Dispatcher(Protocol):
    def register(self, event_type: str, handler: EventHandler) -> None: ...

    async def dispatch(self, event: EventEnvelope) -> None: ...


class InMemoryDispatcher:
    """Synchronous in-process fan-out — tests and local wiring only."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def register(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def dispatch(self, event: EventEnvelope) -> None:
        for handler in self._handlers.get(event.type, []):
            await handler(event)


@dataclass(frozen=True)
class DispatchResult:
    """Per-outcome counts for one ``dispatch_once`` batch."""

    processed: int
    retried: int
    dead_lettered: int

    @property
    def total(self) -> int:
        return self.processed + self.retried + self.dead_lettered


_CLAIM_DUE = text(
    """
    SELECT id, type, version, household_id, occurred_at, payload, attempts
    FROM events_outbox
    WHERE processed_at IS NULL AND next_attempt_at <= now()
    ORDER BY next_attempt_at
    FOR UPDATE SKIP LOCKED
    LIMIT :batch_size
    """
)
_ALREADY = text("SELECT 1 FROM processed_events WHERE handler = :h AND event_id = :e")
_MARK_HANDLER = text(
    "INSERT INTO processed_events (handler, event_id) VALUES (:h, :e) ON CONFLICT DO NOTHING"
)
_MARK_DONE = text("UPDATE events_outbox SET processed_at = now(), last_error = NULL WHERE id = :id")
_RETRY = text(
    "UPDATE events_outbox SET attempts = :att, last_error = :err, "
    "next_attempt_at = now() + make_interval(secs => :secs) WHERE id = :id"
)
_TO_DLQ = text(
    """
    INSERT INTO events_dlq (event_id, type, household_id, payload, attempts, last_error)
    SELECT id, type, household_id, payload, :att, :err FROM events_outbox WHERE id = :id
    """
)
_MARK_DEAD = text(
    "UPDATE events_outbox SET attempts = :att, last_error = :err, processed_at = now() "
    "WHERE id = :id"
)


class OutboxDispatcher:
    """Durable, idempotent, retrying outbox dispatcher (see module docstring)."""

    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_backoff_s: float = DEFAULT_BASE_BACKOFF_S,
    ) -> None:
        self._handlers: dict[str, list[tuple[str, EventHandler]]] = {}
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s

    def register(self, event_type: str, name: str, handler: EventHandler) -> None:
        """Register ``handler`` (identified by a stable ``name``) for ``event_type``.
        The name keys the idempotency ledger — keep it stable across deploys."""
        self._handlers.setdefault(event_type, []).append((name, handler))

    async def dispatch_once(
        self, session: AsyncSession, *, batch_size: int = 100
    ) -> DispatchResult:
        """Claim and process one batch of due events; commit state + ledger once."""
        rows = (await session.execute(_CLAIM_DUE, {"batch_size": batch_size})).mappings().all()
        processed = retried = dead = 0
        for row in rows:
            env = EventEnvelope(
                id=row["id"],
                type=row["type"],
                version=row["version"],
                household_id=row["household_id"],
                occurred_at=row["occurred_at"],
                payload=row["payload"],
            )
            errors = await self._run_handlers(session, env)
            if not errors:
                await session.execute(_MARK_DONE, {"id": env.id})
                processed += 1
                continue
            attempts = int(row["attempts"]) + 1
            err = " | ".join(errors)[:2000]
            if attempts >= self._max_attempts:
                await session.execute(_TO_DLQ, {"id": env.id, "att": attempts, "err": err})
                await session.execute(_MARK_DEAD, {"id": env.id, "att": attempts, "err": err})
                dead += 1
            else:
                secs = self._base_backoff_s * (2 ** (attempts - 1))
                await session.execute(
                    _RETRY, {"id": env.id, "att": attempts, "err": err, "secs": secs}
                )
                retried += 1
        await session.commit()
        return DispatchResult(processed=processed, retried=retried, dead_lettered=dead)

    async def _run_handlers(self, session: AsyncSession, env: EventEnvelope) -> list[str]:
        """Run each not-yet-succeeded handler; record successes immediately. Returns
        the list of error strings (empty == fully delivered)."""
        errors: list[str] = []
        for name, handler in self._handlers.get(env.type, []):
            if await session.scalar(_ALREADY, {"h": name, "e": env.id}):
                continue
            try:
                await handler(env)
            except Exception as exc:  # isolate handler failures — one bad handler ≠ batch
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            await session.execute(_MARK_HANDLER, {"h": name, "e": env.id})
        return errors


@dataclass(frozen=True)
class ReapResult:
    """Rows removed by one reaper pass (ARCHITECTURE §8.4)."""

    outbox: int
    processed_events: int


_REAP_OUTBOX = text(
    "DELETE FROM events_outbox "
    "WHERE processed_at IS NOT NULL AND processed_at < now() - make_interval(days => :days)"
)
_REAP_LEDGER = text(
    "DELETE FROM processed_events WHERE processed_at < now() - make_interval(days => :days)"
)


async def reap(session: AsyncSession, *, retention_days: int) -> ReapResult:
    """Drop processed outbox rows and stale idempotency-ledger entries older than
    ``retention_days`` — the scheduler's hourly cron job (worker.py). Runs as
    ``custode_maint`` so it spans households. Dead-lettered events are untouched: they
    live on in ``events_dlq`` for inspection/replay; only the processed/active-queue rows
    and their ledger entries are removed."""
    outbox = cast(CursorResult[Any], await session.execute(_REAP_OUTBOX, {"days": retention_days}))
    ledger = cast(CursorResult[Any], await session.execute(_REAP_LEDGER, {"days": retention_days}))
    await session.commit()
    return ReapResult(outbox=outbox.rowcount, processed_events=ledger.rowcount)
