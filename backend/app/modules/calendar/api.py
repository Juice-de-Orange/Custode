"""Exported service interface for ``calendar``. The Phase-5 scheduling/fairness logic depends
one-way on this seam (scheduling -> calendar.api): ``list_absences`` surfaces who is away (household
fairness), ``list_busy_intervals`` the occupied slots a viewer must not be double-booked into, and
``list_absence_intervals`` the viewer's own away-times — all without exposing calendar internals.
``sync_all_subscriptions`` (P9-S3) is called only by the worker composition root (the 15-min
CalDAV cron, port injected there — pattern ``digest.api``); no feature module imports it."""

from app.modules.calendar.service import (
    list_absence_intervals,
    list_absences,
    list_busy_intervals,
)
from app.modules.calendar.sync import SyncStats, sync_all_subscriptions

__all__ = [
    "SyncStats",
    "list_absence_intervals",
    "list_absences",
    "list_busy_intervals",
    "sync_all_subscriptions",
]
