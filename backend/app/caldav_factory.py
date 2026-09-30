"""Composition-root factory for the CalDAV port (P9-S3, ADR-0079). Modules and the kernel must
not import adapters (import-linter) — the worker cron receives the composed port from here.
The kill switch (``CUSTODE_CALDAV_SYNC_ENABLED``) selects the Null adapter, which SKIPS every
subscription (raises — an empty answer would trigger the deletion diff and tombstone the
mirrors); the cron additionally short-circuits before enumerating, so "off" truly means no
outbound request and no DB churn."""

from __future__ import annotations

from app.adapters.caldav import CaldavClient
from app.adapters.null import NullCaldav
from app.kernel.ports.caldav import CaldavPort
from app.settings import Settings


def build_caldav(settings: Settings) -> CaldavPort:
    if settings.caldav_sync_enabled:
        return CaldavClient(settings)
    return NullCaldav()
