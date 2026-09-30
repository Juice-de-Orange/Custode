"""Wearable ports (KONZEPT §5.15).

Two separate concerns, deliberately two protocols:

* ``WearableCloudPort`` — reading daily health values (9-S6). Its neutral answer is
  ``UNKNOWN_WEARABLE``: every dependent feature has a full path without wearable data
  (Graceful Enhancement), so "no data" is a weightless signal, not an error.
* ``WearableOAuthPort`` — establishing and refreshing the connection (9-S5). Its neutral
  answer is a RAISE, not a blank: the no-op of an authorisation flow is "refuse", never
  "pretend it worked". Same lesson as ``NullCaldav`` (ADR-0079), where a neutral empty
  answer would have driven a destructive diff.

Health data is Art. 9 GDPR: read-only, only consented types, and never shared with other
members — not even with admins (N-2). The member-scoped RLS in migration 0069 enforces that
in the database; nothing here may widen it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from fastapi import Request
from pydantic import BaseModel


class WearableDaily(BaseModel):
    available: bool = False
    sleep_score: int | None = None
    # Sleep DURATION alongside the score — KONZEPT §5.15 names both ("Schlafdauer & -score");
    # the port previously carried only the score (resolved additively in 9-S5, ADR-0081).
    sleep_minutes: int | None = None
    readiness: int | None = None
    steps: int | None = None
    active_kcal: int | None = None
    rhr: int | None = None


UNKNOWN_WEARABLE = WearableDaily(available=False)


class WearableTokens(BaseModel):
    """The result of an OAuth code exchange / refresh.

    ``expires_at`` is absolute (the adapter converts the provider's relative ``expires_in``)
    so the service stores a value it can filter on in SQL. Everything else is secret and ends
    up inside ONE SecretBox value (``modules/wearables/tokens.py``); this object must never be
    returned in an HTTP response, logged, or put into an event payload."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"  # noqa: S105 — OAuth-Schema-Name, kein Secret
    scopes: list[str] = []
    expires_at: datetime | None = None


class WearableAuthError(Exception):
    """OAuth failure. ``category`` is a short slug (``wearables_disabled`` = Null adapter,
    ``exchange_failed``, ``refresh_failed``, ``unreachable``) — never a token, code, URL or
    response body (all provider-/attacker-influenced)."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class WearableCloudPort(Protocol):
    """Read-only health data (Art. 9 GDPR), only consented types. Never shared
    with other members (N-2).

    Takes the ACCESS TOKEN, not a member id: a cloud adapter has no notion of our members, and
    passing one would invite an adapter to resolve identities it must not know (the 9-S5 stub
    still had ``member_id`` from before OAuth existed). Filtering to consented types happens
    module-side after the fetch — the adapter returns whatever the granted scopes yield.

    Unlike ``WearableOAuthPort``, the neutral answer here is a BLANK (``UNKNOWN_WEARABLE``), not
    a raise: every dependent feature has a full path without wearable data, so "no values" is a
    weightless signal. Implementations raise ``WearableAuthError`` only when the token itself is
    the problem (401/403), so the caller can flag the connection ``needs_reauth``."""

    async def fetch_daily(self, *, access_token: str, day: date) -> WearableDaily: ...


class WearableOAuthPort(Protocol):
    """Authorization-Code flow against the provider (confidential client: the operator
    registers the app, so client id/secret are settings, never per-user)."""

    def authorize_url(self, *, state: str, scopes: list[str], redirect_uri: str) -> str:
        """Build the provider URL the user is sent to. Pure — no I/O, so it stays testable
        without a network and cannot fail halfway through a request."""
        ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> WearableTokens:
        """Trade the callback's one-time code for tokens. ``redirect_uri`` must be byte-identical
        to the one used in ``authorize_url`` — providers verify it."""
        ...

    async def refresh(self, *, refresh_token: str) -> WearableTokens:
        """Exchange a refresh token for a fresh set. Providers may ROTATE the refresh token, so
        the answer REPLACES the stored value wholesale — never merge."""
        ...


def get_wearable_oauth(request: Request) -> WearableOAuthPort:
    """FastAPI dependency: the adapter composed at startup (``app.state.wearable_oauth``) — the
    ``get_caldav``/``get_mail`` pattern, so modules depend only on ``kernel/*`` while the concrete
    adapter is chosen in the composition root (``main.py``)."""
    oauth: WearableOAuthPort = request.app.state.wearable_oauth
    return oauth
