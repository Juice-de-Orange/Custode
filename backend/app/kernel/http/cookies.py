"""Session cookie policy in one place (KONZEPT §8: httpOnly, Secure, SameSite=Lax,
CSRF). Three cookies: access (sent on every request, Path=/), refresh (Path-scoped to
/v1/auth so it never leaks to business routes), and csrf (readable by JS for the
double-submit header). Dev drops Secure + the ``__Host-`` prefix so http://localhost
works; prod uses ``__Host-`` where Path=/ allows it. Read- and write-side share the
name helpers so they can never drift (a mismatch silently breaks logout)."""

from __future__ import annotations

from fastapi import Response

from app.settings import Settings

_REFRESH_PATH = "/v1/auth"


def _secure(settings: Settings) -> bool:
    return settings.env != "dev"


def _prefix(settings: Settings) -> str:
    # __Host- requires Secure + Path=/ + no Domain — only usable once Secure is on.
    return "__Host-" if _secure(settings) else ""


def access_cookie_name(settings: Settings) -> str:
    return f"{_prefix(settings)}custode_at"


def csrf_cookie_name(settings: Settings) -> str:
    return f"{_prefix(settings)}custode_csrf"


def refresh_cookie_name() -> str:
    # Path-scoped to /v1/auth, so it cannot carry __Host- (which forces Path=/).
    return "custode_rt"


def set_access_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        access_cookie_name(settings),
        token,
        max_age=settings.access_token_ttl_s,
        path="/",
        secure=_secure(settings),
        httponly=True,
        samesite="lax",
    )


def set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        refresh_cookie_name(),
        token,
        max_age=settings.refresh_token_ttl_s,
        path=_REFRESH_PATH,
        secure=_secure(settings),
        httponly=True,
        samesite="lax",
    )


def set_csrf_cookie(response: Response, settings: Settings, token: str) -> None:
    # NOT httpOnly: the SPA reads it and echoes it as the X-CSRF-Token header.
    # Lives as long as the refresh session (not the access token): /refresh is
    # CSRF-protected, so the token must still be present after the access TTL lapses.
    response.set_cookie(
        csrf_cookie_name(settings),
        token,
        max_age=settings.refresh_token_ttl_s,
        path="/",
        secure=_secure(settings),
        httponly=False,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Expire all three cookies (logout / theft). Must use the exact name+path they
    were set with, or the browser keeps them and logout silently fails."""
    secure = _secure(settings)
    response.delete_cookie(access_cookie_name(settings), path="/", secure=secure, samesite="lax")
    response.delete_cookie(
        csrf_cookie_name(settings), path="/", secure=secure, httponly=False, samesite="lax"
    )
    response.delete_cookie(refresh_cookie_name(), path=_REFRESH_PATH, secure=secure, samesite="lax")


_PASSKEY_FLOW_PATH = "/v1/auth/passkeys"


def passkey_flow_cookie_name() -> str:
    return "custode_pk_flow"


def set_passkey_flow_cookie(response: Response, settings: Settings, flow_id: str) -> None:
    """Short-lived httpOnly cookie binding a passwordless-login challenge to the client."""
    response.set_cookie(
        passkey_flow_cookie_name(),
        flow_id,
        max_age=300,
        path=_PASSKEY_FLOW_PATH,
        secure=_secure(settings),
        httponly=True,
        samesite="lax",
    )


def clear_passkey_flow_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        passkey_flow_cookie_name(),
        path=_PASSKEY_FLOW_PATH,
        secure=_secure(settings),
        samesite="lax",
    )
