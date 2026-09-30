"""Oura OAuth2 adapter (P9-S5, ADR-0081) — Authorization Code, confidential client.

The operator registers one app, so client id/secret are deployment settings and we can
authenticate the token exchange with the secret. The hosts are FIXED (``cloud.ouraring.com`` /
``api.ouraring.com``): no user-supplied URL, therefore not the SSRF surface that
``kernel/fetch`` guards — same reasoning as the Open-Meteo and GitHub adapters, which also use
``httpx`` directly.

No retry layer, deliberately: the repo has none anywhere. A failed exchange is a user-visible
error they can retry by clicking again; a failed refresh is picked up by the next cron tick
(9-S6).

Every failure becomes a ``WearableAuthError`` with a short category. Provider response bodies
are never logged or surfaced — they may echo the code/token back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.kernel.ports.wearable import WearableAuthError, WearableTokens
from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.oura")

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"  # noqa: S105 — Endpunkt-URL, kein Secret

# Oura scope names. Deliberately COARSER than our consent vocabulary: the user consents per
# data type (KONZEPT §5.15), and ``daily`` happens to cover sleep/readiness/activity at the
# provider. modules/wearables/types.py owns the mapping.
SCOPE_DAILY = "daily"
SCOPE_HEARTRATE = "heartrate"
SCOPE_PERSONAL = "personal"


class OuraOAuth:
    def __init__(self, settings: Settings) -> None:
        # The factory only builds this with both set; guard (and narrow the type) defensively,
        # mirroring GitHubIssueTracker.
        if settings.oura_client_id is None or settings.oura_client_secret is None:
            raise ValueError("OuraOAuth requires oura_client_id and oura_client_secret")
        self._client_id = settings.oura_client_id
        self._client_secret = settings.oura_client_secret
        self._timeout = settings.oura_timeout_s

    def authorize_url(self, *, state: str, scopes: list[str], redirect_uri: str) -> str:
        """Pure URL builder — no I/O, so the whole shape is unit-testable without a network."""
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(scopes),
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> WearableTokens:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                # Must be byte-identical to the one in authorize_url — providers verify it.
                "redirect_uri": redirect_uri,
            },
            category="exchange_failed",
        )

    async def refresh(self, *, refresh_token: str) -> WearableTokens:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            category="refresh_failed",
        )

    async def _token_request(self, form: dict[str, str], *, category: str) -> WearableTokens:
        payload = {**form, "client_id": self._client_id, "client_secret": self._client_secret}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(TOKEN_URL, data=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            # Failure CLASS only — the body may contain the code or a token.
            _log.warning("oura_token_request_failed", error=type(exc).__name__, category=category)
            raise WearableAuthError(category) from exc
        except ValueError as exc:  # non-JSON body
            _log.warning("oura_token_response_not_json", category=category)
            raise WearableAuthError(category) from exc
        return _parse_tokens(data, category=category)


def _parse_tokens(data: object, *, category: str) -> WearableTokens:
    """Map a token response onto ``WearableTokens``.

    Tolerant of unknown extra fields (forward compatibility, ARCHITECTURE §8.2) but strict about
    ``access_token`` — without it there is nothing to store. ``expires_in`` is converted to an
    absolute instant here so the service (and the 9-S6 cron's SQL filter) never has to reason
    about when the response arrived."""
    if not isinstance(data, dict) or not isinstance(data.get("access_token"), str):
        raise WearableAuthError(category)
    expires_at: datetime | None = None
    expires_in = data.get("expires_in")
    if isinstance(expires_in, int | float) and not isinstance(expires_in, bool):
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
    raw_scope = data.get("scope")
    scopes = raw_scope.split() if isinstance(raw_scope, str) else []
    refresh = data.get("refresh_token")
    token_type = data.get("token_type")
    return WearableTokens(
        access_token=data["access_token"],
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        token_type=token_type if isinstance(token_type, str) and token_type else "Bearer",
        scopes=scopes,
        expires_at=expires_at,
    )
