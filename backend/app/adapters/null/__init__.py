"""Null adapters — the neutral, always-available implementation of every port.
Domain logic treats their answers as a weightless/neutral signal."""

from __future__ import annotations

from datetime import date

from app.kernel.ports.caldav import CaldavAuth, CaldavError, CaldavObject
from app.kernel.ports.llm import UNAVAILABLE_LLM, LlmResult
from app.kernel.ports.wearable import (
    UNKNOWN_WEARABLE,
    WearableAuthError,
    WearableDaily,
    WearableTokens,
)
from app.kernel.ports.weather import UNKNOWN_FORECAST, Forecast
from app.logging import get_logger

_log = get_logger("adapters.null")


class NullWeather:
    async def forecast(self, *, lat: float, lon: float, day: str) -> Forecast:
        return UNKNOWN_FORECAST


class NullLlm:
    async def extract(self, *, prompt: str, schema: dict[str, object]) -> LlmResult:
        return UNAVAILABLE_LLM


class NullPush:
    async def send(self, *, user_id: str, title: str, body: str) -> bool:
        _log.debug("null_push_dropped", user_id=user_id)
        return True  # accepted as no-op


class NullMail:
    async def send(self, *, to: str, subject: str, body_md: str) -> bool:
        _log.debug("null_mail_dropped", to=to)
        return True  # accepted as no-op


class NullIssueTracker:
    async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
        # No tracker configured -> forwarding is off. Accept as a no-op (no outbound call, no PII).
        _log.debug("null_issue_dropped")
        return True


class NullStorage:
    async def presign_put(self, *, path: str, content_type: str) -> str:
        return f"about:blank#put/{path}"

    async def presign_get(self, *, path: str) -> str:
        return f"about:blank#get/{path}"


class NullPayments:
    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        return False  # safe default: reject unverifiable webhooks


class NullWearable:
    # Data path: a BLANK is the correct neutral answer (unlike NullWearableOAuth, which refuses).
    # Every dependent feature has a full path without wearable values — "no data" is weightless,
    # not an error, so the ingest run simply stores nothing (Graceful Enhancement, KONZEPT §5.15).
    async def fetch_daily(self, *, access_token: str, day: date) -> WearableDaily:
        return UNKNOWN_WEARABLE


class NullWearableOAuth:
    # Stand-in when the provider is switched off or has no credentials (P9-S5). Deliberately
    # RAISES on every method, including the pure URL builder — the neutral no-op of an
    # authorisation flow is "refuse", not "hand out a URL that leads nowhere". Sending a user
    # to a provider consent screen that cannot be completed would leave a dangling grant in
    # their account. Same lesson as NullCaldav, one layer earlier.
    def authorize_url(self, *, state: str, scopes: list[str], redirect_uri: str) -> str:
        raise WearableAuthError("wearables_disabled")

    async def exchange_code(self, *, code: str, redirect_uri: str) -> WearableTokens:
        raise WearableAuthError("wearables_disabled")

    async def refresh(self, *, refresh_token: str) -> WearableTokens:
        raise WearableAuthError("wearables_disabled")


class NullCaldav:
    # Kill-switch stand-in (sync disabled). Deliberately RAISES instead of returning [] — the
    # port contract reads an empty list as "collection is empty", which would make the sync's
    # deletion diff tombstone every mirrored event. The neutral no-op for a diff-based sync is
    # "touch nothing", i.e. a per-subscription skip. Write ops raise too (P9-S4): with the
    # switch off, a mirror edit answers 503 instead of silently diverging from the remote.
    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]:
        raise CaldavError("sync_disabled")

    async def get_object(self, *, url: str, href: str, auth: CaldavAuth) -> CaldavObject:
        raise CaldavError("sync_disabled")

    async def put_object(
        self,
        *,
        url: str,
        href: str,
        ics_text: str,
        etag: str | None,
        if_none_match: bool,
        auth: CaldavAuth,
    ) -> str | None:
        raise CaldavError("sync_disabled")

    async def delete_object(
        self, *, url: str, href: str, etag: str | None, auth: CaldavAuth
    ) -> None:
        raise CaldavError("sync_disabled")
