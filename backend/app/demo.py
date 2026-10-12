"""Public demo mode (``CUSTODE_DEMO_MODE=on``, docs/demo.md) — the request-side wall.

The demo runs on the internet with one shared household and a login everybody can read off the
sign-in page. Two rules shape everything here:

* **Nothing a visitor does may reach beyond the instance or outlive the hour.** Every path that
  creates accounts, sends mail, stores files, exports to the outside, imports from it or would
  lock the shared account (TOTP, passkeys, profile, sessions, membership changes) answers
  ``403 demo_disabled`` — refused **here, before routing**, not merely hidden in the UI. The
  settings layer additionally switches every external adapter to its Null variant
  (``Settings._demo_switches_off_the_outside``), so a path this list missed still has no way out.
* **Nobody may exhaust the host.** Per-IP fixed-window rate limit in Redis, a cap on the request
  body, and no long-lived SSE connections (the PWA falls back to refetch-on-focus).

The composition root owns this list on purpose: it is the one place that may name every module's
routes, and a reviewer can read the whole demo surface in one table. Off means off: ``create_app``
installs neither the middleware nor the demo's ``/v1/demo`` route unless the flag is set — a
normal instance answers ``/v1/demo`` with ``{"enabled": false}`` only, so the web's one question
per page load is not a 404 in every visitor's console.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.kernel.http.problem import ProblemException, problem_response
from app.kernel.redis import get_redis
from app.logging import get_logger
from app.settings import Settings

#: Redis flag set by ``demo-reset`` while it restores the seed (the banner says "resetting").
RESETTING_KEY = "demo:resetting"
_RATE_PREFIX = "demo:rl:"

_ANY = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: (methods, path pattern, why). Patterns are anchored; ``[^/]+`` is one path segment.
BLOCKED: tuple[tuple[frozenset[str], str, str], ...] = (
    # Accounts: no new accounts, no mail, nothing that would lock or rename the shared login.
    (_WRITE, r"/v1/auth/register", "sign-up"),
    (_WRITE, r"/v1/auth/password/(forgot|reset)", "password reset (mail)"),
    (_WRITE, r"/v1/auth/email/verify/(request|confirm)", "e-mail verification (mail)"),
    (_WRITE, r"/v1/auth/totp/[^/]+", "second factor on the shared account"),
    (_WRITE, r"/v1/auth/passkeys/register/[^/]+", "passkey on the shared account"),
    (_WRITE, r"/v1/auth/passkeys/[^/]+", "passkey removal"),
    (_WRITE, r"/v1/auth/account", "account deletion"),
    (_WRITE, r"/v1/auth/sessions/[^/]+", "signing other visitors out"),
    (_WRITE, r"/v1/account/profile", "profile of the shared account"),
    # Households: no invites, no new or dissolved households, no membership changes.
    (_WRITE, r"/v1/households", "new household"),
    (_WRITE, r"/v1/households/join", "invites"),
    (_WRITE, r"/v1/household/invites", "invites"),
    (_WRITE, r"/v1/household/children", "child accounts"),
    (_WRITE, r"/v1/household/members/[^/]+", "membership changes"),
    (_WRITE, r"/v1/household/(leave|dissolve)", "leaving or dissolving the demo household"),
    (_WRITE, r"/v1/household/digest", "digest e-mail"),
    # Files and imports from the outside.
    (_WRITE, r"/v1/recipes/import", "recipe import from a URL (outbound fetch)"),
    (_WRITE, r"/v1/recipes/[^/]+/photo", "uploads"),
    (_WRITE, r"/v1/guides/[^/]+/attachments(/[^/]+)?", "uploads"),
    (_WRITE, r"/v1/calendar/import", "calendar file import"),
    # Calendar to and from the outside: ICS feeds and CalDAV subscriptions.
    (_ANY, r"/v1/calendar/feed(/[^/]+)?", "ICS export feed"),
    (_WRITE, r"/v1/calendar/subscriptions(/[^/]+)?(/check)?", "CalDAV sync"),
    # Integrations.
    (_ANY, r"/v1/vault(/.*)?", "vault"),
    (_WRITE, r"/v1/wearables/.*", "Oura"),
    (_ANY, r"/v1/wearables/oura/callback", "Oura"),
    (_ANY, r"/v1/weather/geocode", "weather (outbound)"),
    (_WRITE, r"/v1/weather/location", "weather (outbound)"),
    (_WRITE, r"/v1/feedback", "feedback forwarding"),
    # Long-lived connections and the operator console.
    (_ANY, r"/v1/stream", "live updates (long-lived connections)"),
    (_ANY, r"/ops(/.*)?", "operator console"),
)

_COMPILED: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = tuple(
    (methods, re.compile(pattern)) for methods, pattern, _ in BLOCKED
)

#: Never rate-limited: probes must stay green while visitors are throttled.
_UNLIMITED = frozenset({"/healthz", "/readyz", "/v1/demo"})


def is_blocked(method: str, path: str) -> bool:
    """True when demo mode refuses this request."""
    return any(method in methods and pattern.fullmatch(path) for methods, pattern in _COMPILED)


def client_key(request: Request, header: str) -> str:
    """The visitor's address: the trusted edge header when configured and present, else the peer."""
    if header:
        value = request.headers.get(header, "").strip()
        if value:
            return value
    return request.client.host if request.client else "unknown"


def _disabled() -> ProblemException:
    return ProblemException(
        slug="demo_disabled",
        title="Not available in the demo",
        status=403,
        detail="This public demo does not allow this action. Run your own instance to use it.",
    )


class DemoModeMiddleware(BaseHTTPMiddleware):
    """Refuse the blocked paths, cap bodies, rate-limit per IP, mark every answer ``noindex``."""

    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await self._guard(request)
        if response is None:
            response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    async def _guard(self, request: Request) -> Response | None:
        settings = self._settings
        path = request.url.path
        if is_blocked(request.method, path):
            return problem_response(request, _disabled())

        length = request.headers.get("content-length")
        if length is not None and (
            not length.isdigit() or int(length) > settings.demo_max_body_bytes
        ):
            return problem_response(
                request,
                ProblemException(
                    slug="demo_payload_too_large",
                    title="Request too large for the demo",
                    status=413,
                    detail=f"The demo accepts at most {settings.demo_max_body_bytes} bytes.",
                ),
            )

        if path in _UNLIMITED:
            return None
        window = settings.demo_rate_window_s
        bucket = int(time.time()) // window
        key = f"{_RATE_PREFIX}{client_key(request, settings.demo_client_ip_header)}:{bucket}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window * 2)
        except Exception as exc:  # Redis down: the demo stays usable, the limit is best effort
            get_logger("demo").warning("demo_rate_limit_unavailable", error=type(exc).__name__)
            return None
        if count > settings.demo_rate_limit:
            response = problem_response(
                request,
                ProblemException(
                    slug="demo_rate_limited",
                    title="Too many requests",
                    status=429,
                    detail="The demo limits requests per visitor. Please wait a few seconds.",
                ),
            )
            response.headers["Retry-After"] = str(window - int(time.time()) % window)
            return response
        return None


demo_router = APIRouter(tags=["demo"])
no_demo_router = APIRouter(tags=["demo"])


@no_demo_router.get("/v1/demo", include_in_schema=False)
async def no_demo() -> dict[str, object]:
    """A normal instance: no demo, nothing else to say (``web/src/lib/demo.ts``)."""
    return {"enabled": False}


@demo_router.get("/v1/demo", include_in_schema=False)
async def demo_info(request: Request) -> dict[str, object]:
    """What the sign-in page and the banner need. Not in the OpenAPI schema (like ``/healthz``):
    its answer differs between demo and normal instances, and the web reads it with a plain
    ``fetch``. The credentials are public by design — they are on the sign-in page."""
    from app.scripts.seed_demo import DEMO_EMAIL, DEMO_PASSWORD

    try:
        resetting = bool(await get_redis().exists(RESETTING_KEY))
    except Exception:
        resetting = False
    settings: Settings = request.app.state.settings
    return {
        "enabled": True,
        "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD,
        "reset_interval_minutes": 60,
        "resetting": resetting,
        "max_body_bytes": settings.demo_max_body_bytes,
    }


def install_demo_mode(app: FastAPI, settings: Settings) -> None:
    """Wire demo mode into the app; without ``CUSTODE_DEMO_MODE`` only the "no demo" answer."""
    if not settings.demo_mode:
        app.include_router(no_demo_router)
        return
    app.add_middleware(DemoModeMiddleware, settings=settings)
    app.include_router(demo_router)
    get_logger("demo").info("demo_mode_on", blocked_paths=len(BLOCKED))
