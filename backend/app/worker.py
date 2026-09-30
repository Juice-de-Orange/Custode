"""taskiq worker + scheduler (ARCHITECTURE §8.4). Delivery guarantees come from the
outbox + processed_events ledger (at-least-once + idempotency), not from the broker.

One module, two roles of the api/worker/scheduler deployable trio:

* ``worker`` (``taskiq worker app.worker:broker``) runs the **event dispatcher** as an
  in-process loop started on ``WORKER_STARTUP``. It drains ``events_outbox`` every
  ``outbox_poll_interval_s`` so the SSE invalidation hints added in S3/S4 land with ~1 s
  latency — well under cron granularity. Concurrent workers are safe: ``dispatch_once``
  claims rows ``FOR UPDATE SKIP LOCKED``.
* ``scheduler`` (``taskiq scheduler app.worker:scheduler``) fires cron tasks. For now the
  hourly **outbox reaper**; weather/wearable/escrow jobs join later (§8.4).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker

from app.account_purge import run_purge
from app.caldav_factory import build_caldav
from app.household_dissolution import register_household_dissolution_handler
from app.household_purge import run_purge as run_household_purge
from app.issue_factory import build_issue_tracker
from app.kernel.db.engine import get_maint_sessionmaker
from app.kernel.events.dispatcher import reap
from app.kernel.events.registry import get_dispatcher
from app.kernel.redis import close_redis
from app.kernel.retention.reaper import reap_deleted
from app.kernel.sync.reaper import reap_sync_ops
from app.logging import get_logger
from app.mail_factory import build_mail
from app.member_exit import register_member_exit_handler
from app.modules.calendar import api as calendar_api
from app.modules.calendar.handlers import register_calendar_handlers
from app.modules.capture.handlers import register_capture_handlers
from app.modules.comments.handlers import register_comments_handlers
from app.modules.digest import api as digest_api
from app.modules.feedback.handlers import register_feedback_handlers
from app.modules.links.handlers import register_links_handlers
from app.modules.wearables import api as wearables_api
from app.modules.wearables.handlers import register_wearables_handlers
from app.settings import get_settings, require_runtime_settings
from app.wearable_factory import build_wearable_cloud, build_wearable_oauth

_settings = get_settings()
require_runtime_settings(_settings)  # dispatcher + reaper need the maint role (BUGLOG 2026-06-17)
broker = ListQueueBroker(url=_settings.redis_url)
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])

_log = get_logger("worker.outbox")
# Cap one wake-up's work so the loop stays responsive to shutdown even under a backlog.
_MAX_DRAIN_BATCHES = 50

# Allow-list of tables the retention reaper hard-deletes tombstones from (ARCHITECTURE §9). Defined
# here at the composition root — the kernel reaper must not import module models (E2). A table joins
# this list once it has a user-facing soft-delete (and, later, a trash/restore surface); child rows
# cascade via FK ON DELETE CASCADE (e.g. note_versions). Append-only/audit data (points ledger,
# audit_log) and non-deletable types (letters) are never listed — those rows are never tombstoned,
# so **this** job must never touch them. ``notes`` is the first; more join as they gain a delete +
# trash.
# Abgrenzung, seit 11-S1d/11-S1f nötig: „nie hard-deleted" gilt für den *Reaper*, nicht absolut.
# Der Konto-Purge (03:30) und der Haushalts-Purge (04:00) löschen `points_ledger` und `letters`
# sehr wohl — der eine, weil die Person geht, der andere, weil der Mandant endet (ADR-0086 §6).
# Beide arbeiten auf einer anderen Achse als hier: nicht „Alter des Tombstones", sondern „dieses
# Konto" bzw. „dieser Haushalt".
# P9-S3: CalDAV subscriptions tombstone on unsubscribe (their mirror events cascade via FK on the
# hard delete); ``calendar_events`` joins too — mirror rows tombstoned by the sync diff (and
# user-deleted local events, which now purge after the same 30-day window, ARCH §9).
_RETENTION_TABLES: tuple[str, ...] = ("notes", "external_calendar_subscriptions", "calendar_events")

_dispatch_stop: asyncio.Event | None = None
_dispatch_task: asyncio.Task[None] | None = None


@broker.task
async def ping() -> str:
    return "pong"


async def drain_outbox(sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> int:
    """Drain due outbox events in batches until the queue is idle (or the batch cap is hit).
    Each batch runs in its own maint session — ``dispatch_once`` commits the dispatch state and
    the idempotency ledger together. Returns the number of events touched."""
    dispatcher = get_dispatcher()
    factory = sessionmaker or get_maint_sessionmaker()
    total = 0
    for _ in range(_MAX_DRAIN_BATCHES):
        async with factory() as session:
            result = await dispatcher.dispatch_once(session)
        total += result.total
        if result.dead_lettered:
            _log.warning("outbox_dead_lettered", count=result.dead_lettered)  # count only, no PII
        if result.total == 0:
            break
    return total


async def _dispatch_loop(stop: asyncio.Event) -> None:
    interval = get_settings().outbox_poll_interval_s
    while not stop.is_set():
        try:
            await drain_outbox()
        except Exception:  # a bad cycle (DB blip, handler bug) must not kill the loop
            _log.exception("outbox_dispatch_cycle_failed")
        # Sleep until the next poll, or wake immediately when shutdown sets the event.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start_dispatch_loop(state: TaskiqState) -> None:
    global _dispatch_stop, _dispatch_task
    # App composition root: bind module-provided outbox handlers onto the kernel dispatcher (the
    # kernel must not import modules, so this lives here — ADR-0039). Idempotent per stable name.
    register_capture_handlers(get_dispatcher())
    register_comments_handlers(get_dispatcher())
    register_links_handlers(get_dispatcher())
    # Austritt aus einem Haushalt (KONZEPT §5.1): der Zugang endet überall, nicht nur in der
    # Mitgliedschaftszeile. Feed-Token + CalDAV-Abos (calendar), Art.-9-Daten (wearables).
    register_calendar_handlers(get_dispatcher())
    register_wearables_handlers(get_dispatcher())
    # Der Ökonomie-Teil des Austritts — Reihenfolge und Begründung in app/member_exit.py.
    register_member_exit_handler(get_dispatcher())
    register_household_dissolution_handler(get_dispatcher())
    # Feedback → issue-tracker forwarder (ADR-0076). Tracker chosen from settings here (the module +
    # kernel must not import adapters); Null when unconfigured, so this is inert by default.
    register_feedback_handlers(get_dispatcher(), build_issue_tracker(_settings))
    stop = asyncio.Event()
    _dispatch_stop = stop
    _dispatch_task = asyncio.create_task(_dispatch_loop(stop))
    _log.info("outbox_dispatcher_started", poll_interval_s=_settings.outbox_poll_interval_s)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _stop_dispatch_loop(state: TaskiqState) -> None:
    if _dispatch_stop is not None:
        _dispatch_stop.set()
    task = _dispatch_task
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            pass
        except Exception:  # never let shutdown raise
            _log.exception("outbox_dispatcher_stop_error")
    await close_redis()
    _log.info("outbox_dispatcher_stopped")


@broker.task(schedule=[{"cron": "0 * * * *"}])
async def reap_outbox() -> None:
    """Hourly cron (scheduler-fired, worker-run): drop processed outbox rows and stale
    idempotency-ledger entries older than ``outbox_retention_days`` (ARCHITECTURE §8.4)."""
    settings = get_settings()
    factory = get_maint_sessionmaker()
    async with factory() as session:
        result = await reap(session, retention_days=settings.outbox_retention_days)
    if result.outbox or result.processed_events:
        _log.info("outbox_reaped", outbox=result.outbox, processed_events=result.processed_events)


@broker.task(schedule=[{"cron": "30 * * * *"}])
async def reap_sync_ops_job() -> None:
    """Hourly cron (offset from the outbox reaper): drop Sync-Batch idempotency markers older than
    ``sync_ops_retention_days`` (ARCH §8.4/§10). Runs as ``custode_maint`` (spans households)."""
    settings = get_settings()
    factory = get_maint_sessionmaker()
    async with factory() as session:
        removed = await reap_sync_ops(session, retention_days=settings.sync_ops_retention_days)
    if removed:
        _log.info("sync_ops_reaped", count=removed)


@broker.task(schedule=[{"cron": "30 3 * * *"}])
async def purge_due_accounts_job() -> None:
    """Naechtlicher Cron (Art. 17): Konten, deren Karenz abgelaufen ist, endgueltig ausraeumen.

    Versetzt zum Retention-Reaper um 03:00 — beide laufen als ``custode_maint`` und fassen zum Teil
    dieselben Tabellen an; gleichzeitig zu starten waere unnoetiges Sperrgeraufe.

    Die Reihenfolge ist ebenfalls Absicht: erst der Reaper (Tombstones), dann der Purge. Ein Konto,
    dessen persoenliche Zeilen der Reaper ohnehin schon geholt hat, kostet den Purge weniger — und
    andersherum wuerde der Purge Zeilen anfassen, die eine halbe Stunde spaeter ohnehin fielen.

    Der Composition Root (``app.account_purge``) protokolliert Wirkung UND Fehlschlag; hier steht
    bewusst kein zweites Logging daneben.
    """
    await run_purge(retention_days=get_settings().retention_days)


@broker.task(schedule=[{"cron": "0 4 * * *"}])
async def purge_due_households_job() -> None:
    """Naechtlicher Cron (Art. 17, 11-S1f): aufgeloeste Haushalte endgueltig ausraeumen.

    Um 04:00 und damit **nach** dem Konto-Purge (03:30). Die Reihenfolge ist Absicht: der
    Konto-Purge raeumt personenbezogene Zeilen quer ueber alle Haushalte weg, der Haushalts-Purge
    danach den Rest eines beendeten Mandanten. Andersherum fasste der Konto-Purge Tabellen an, die
    eine halbe Stunde zuvor ohnehin gefallen waeren.

    Der Composition Root (``app.household_purge``) protokolliert Wirkung UND Fehlschlag; hier steht
    bewusst kein zweites Logging daneben.
    """
    await run_household_purge(retention_days=get_settings().retention_days)


@broker.task(schedule=[{"cron": "0 3 * * *"}])
async def reap_deleted_job() -> None:
    """Daily off-peak cron: hard-delete soft-deleted rows whose ``deleted_at`` is older than
    ``retention_days`` — the 30-day trash window (ARCH §9). Runs as ``custode_maint`` (spans
    households). Logs per-table aggregate counts only, never row contents (no PII)."""
    settings = get_settings()
    factory = get_maint_sessionmaker()
    async with factory() as session:
        result = await reap_deleted(
            session, retention_days=settings.retention_days, tables=_RETENTION_TABLES
        )
    if result.failed:
        # Alarmfähig: eine übersprungene Tabelle sieht sonst aus wie eine ohne fällige Zeilen.
        # Genau diese Stille hat den Ausfall von BUGLOG 2026-07-31 drei Wochen lang getragen.
        _log.error("retention_tables_failed", **result.failed)
    if result.total:
        _log.info("retention_reaped", total=result.total, **result.removed)


@broker.task(schedule=[{"cron": "5,20,35,50 * * * *"}])
async def sync_external_calendars_job() -> None:
    """15-min cron (offset from the :00/:30 reapers): pull every enabled CalDAV subscription and
    mirror its events (P9-S3, ADR-0079). Kill switch first — off means no enumeration, no outbound
    request. Enumerates under ``custode_maint`` (SELECT-only), writes per household under the
    owner's scoped session (RLS). Logs aggregate counts only — never URLs/credentials/content."""
    settings = get_settings()
    if not settings.caldav_sync_enabled:
        return
    await calendar_api.sync_all_subscriptions(caldav=build_caldav(settings), now=datetime.now(UTC))


@broker.task(schedule=[{"cron": "20 4 * * *"}])
async def ingest_wearables_job() -> None:
    """Nightly cron (off-peak, offset from the 03:00/03:40 reapers): pull each active wearable
    connection's daily values (P9-S6, ADR-0081). Kill switch first — off means the Null adapter,
    which fetches nothing, so no outbound request and no stored row.

    Enumerates under ``custode_maint`` (SELECT-only) and writes per member under the owner's
    scoped session: the member-scoped RLS deliberately denies the maint role any write here, so
    N-2 holds for the background job too. Logs aggregate counts only — never tokens or values."""
    settings = get_settings()
    if not settings.oura_enabled:
        return
    await wearables_api.ingest_all(
        cloud=build_wearable_cloud(settings),
        oauth=build_wearable_oauth(settings),
        now=datetime.now(UTC),
    )


@broker.task(schedule=[{"cron": "40 3 * * *"}])
async def reap_wearable_daily_job() -> None:
    """Daily off-peak cron: hard-delete raw wearable values older than
    ``wearable_raw_retention_days`` (KONZEPT §11, Default 90 Tage).

    Runs **regardless of the kill switch**: data must age out even when no new data arrives.
    Separate from ``reap_deleted_job`` because that one purges by ``deleted_at`` while these
    tables forbid tombstones — the axis here is the age of the measured day. Runs as
    ``custode_maint`` (DELETE granted in migration 0070)."""
    settings = get_settings()
    factory = get_maint_sessionmaker()
    async with factory() as session:
        removed = await wearables_api.reap_wearable_daily(
            session, retention_days=settings.wearable_raw_retention_days
        )
    if removed:
        _log.info("wearable_daily_reaped", count=removed)


@broker.task(schedule=[{"cron": "0 7 * * 1"}])
async def send_weekly_digest_job() -> None:
    """Weekly cron (Mon 07:00): e-mail each household its weekly overview (Roadmap Phase 8). Runs as
    ``custode_maint`` (spans households). Graceful — the Null mail adapter sends nothing. Logs only
    an aggregate count, never recipients (no PII)."""
    settings = get_settings()
    mail = build_mail(settings)
    factory = get_maint_sessionmaker()
    async with factory() as session:
        sent = await digest_api.send_weekly_digests(
            session, mail=mail, brand=settings.brand_name, now=datetime.now(UTC)
        )
    if sent:
        _log.info("weekly_digest_sent", count=sent)
