"""Composition-root factory for the wearable OAuth port (P9-S5, ADR-0081). Modules and the
kernel must not import adapters (import-linter), so the concrete adapter is chosen here.

Two independent reasons to fall back to the Null adapter, both ending in a graceful 503 rather
than a crash: the operator-level kill switch (``CUSTODE_OURA_ENABLED``, KONZEPT §11 requires one
per external adapter) and missing credentials (the ``issue_factory`` pattern — an integration
without its secrets is simply off)."""

from __future__ import annotations

from app.adapters.null import NullWearable, NullWearableOAuth
from app.adapters.oura import OuraClient, OuraOAuth
from app.kernel.ports.wearable import WearableCloudPort, WearableOAuthPort
from app.settings import Settings


def _configured(settings: Settings) -> bool:
    return bool(settings.oura_enabled and settings.oura_client_id and settings.oura_client_secret)


def build_wearable_oauth(settings: Settings) -> WearableOAuthPort:
    return OuraOAuth(settings) if _configured(settings) else NullWearableOAuth()


def build_wearable_cloud(settings: Settings) -> WearableCloudPort:
    """Data port for the ingest cron (P9-S6). Same switch as the OAuth port — a run with the
    Null adapter fetches nothing and therefore stores nothing, which is the correct neutral
    behaviour here (unlike the OAuth port, which refuses)."""
    return OuraClient(settings) if _configured(settings) else NullWearable()
