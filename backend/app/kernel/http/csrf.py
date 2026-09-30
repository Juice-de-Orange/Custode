"""CSRF double-submit (KONZEPT §8). Unsafe requests must echo the CSRF cookie in the
``X-CSRF-Token`` header; cookie and header must match (constant-time). Safe methods
are exempt. The CSRF cookie itself is set in ``cookies.py`` (not httpOnly)."""

from __future__ import annotations

import secrets

from fastapi import Request

from app.kernel.http.cookies import csrf_cookie_name
from app.kernel.http.problem import ProblemException
from app.settings import get_settings

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_HEADER = "x-csrf-token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def require_csrf(request: Request) -> None:
    """FastAPI dependency: enforce double-submit CSRF on unsafe methods. Raises 403
    on a missing or mismatched token."""
    if request.method in _SAFE_METHODS:
        return
    cookie = request.cookies.get(csrf_cookie_name(get_settings()))
    header = request.headers.get(_CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise ProblemException(
            slug="csrf_failed",
            title="CSRF-Prüfung fehlgeschlagen",
            status=403,
            detail="Fehlendes oder ungültiges CSRF-Token.",
        )
