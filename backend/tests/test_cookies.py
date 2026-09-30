"""Cookie-policy unit tests (no infra): dev vs. prod flags, names, and clearing."""

from __future__ import annotations

from fastapi import Response

from app.kernel.http.cookies import (
    access_cookie_name,
    clear_auth_cookies,
    csrf_cookie_name,
    refresh_cookie_name,
    set_access_cookie,
    set_csrf_cookie,
    set_refresh_cookie,
)
from app.settings import Settings

DEV = Settings(env="dev")
PROD = Settings(env="prod")


def _header_for(resp: Response, name: str) -> str | None:
    for h in resp.headers.getlist("set-cookie"):
        if h.startswith(f"{name}="):
            return h
    return None


def test_dev_access_cookie_flags() -> None:
    resp = Response()
    set_access_cookie(resp, DEV, "tok")
    h = _header_for(resp, "custode_at")
    assert h is not None
    assert "HttpOnly" in h
    assert "SameSite=lax" in h
    assert "Path=/" in h
    assert "Secure" not in h


def test_prod_access_cookie_is_host_prefixed_and_secure() -> None:
    resp = Response()
    set_access_cookie(resp, PROD, "tok")
    h = _header_for(resp, "__Host-custode_at")
    assert h is not None
    assert "Secure" in h
    assert "HttpOnly" in h
    assert "Path=/" in h


def test_csrf_cookie_not_httponly() -> None:
    resp = Response()
    set_csrf_cookie(resp, DEV, "csrf")
    h = _header_for(resp, "custode_csrf")
    assert h is not None
    assert "HttpOnly" not in h


def test_refresh_cookie_path_scoped() -> None:
    resp = Response()
    set_refresh_cookie(resp, DEV, "rt")
    h = _header_for(resp, "custode_rt")
    assert h is not None
    assert "Path=/v1/auth" in h
    assert "HttpOnly" in h


def test_names_match_env() -> None:
    assert access_cookie_name(DEV) == "custode_at"
    assert access_cookie_name(PROD) == "__Host-custode_at"
    assert csrf_cookie_name(PROD) == "__Host-custode_csrf"
    assert refresh_cookie_name() == "custode_rt"


def test_clear_expires_all_three() -> None:
    resp = Response()
    clear_auth_cookies(resp, DEV)
    headers = resp.headers.getlist("set-cookie")
    assert any(c.startswith("custode_at=") for c in headers)
    assert any(c.startswith("custode_csrf=") for c in headers)
    assert any(c.startswith("custode_rt=") for c in headers)
    assert all("Max-Age=0" in c or "01 Jan 1970" in c for c in headers)
