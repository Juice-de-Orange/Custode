"""CSRF double-submit unit tests (no infra)."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException


def _request(method: str, *, cookie: str | None = None, header: str | None = None) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = []
    if cookie is not None:
        raw_headers.append((b"cookie", f"custode_csrf={cookie}".encode()))
    if header is not None:
        raw_headers.append((b"x-csrf-token", header.encode()))
    scope: dict[str, Any] = {"type": "http", "method": method, "path": "/", "headers": raw_headers}
    return Request(scope)


async def test_safe_method_exempt() -> None:
    await require_csrf(_request("GET"))


async def test_matching_token_passes() -> None:
    await require_csrf(_request("POST", cookie="abc123", header="abc123"))


async def test_missing_header_rejected() -> None:
    with pytest.raises(ProblemException) as ei:
        await require_csrf(_request("POST", cookie="abc123"))
    assert ei.value.status == 403
    assert ei.value.slug == "csrf_failed"


async def test_mismatch_rejected() -> None:
    with pytest.raises(ProblemException) as ei:
        await require_csrf(_request("POST", cookie="abc123", header="zzz999"))
    assert ei.value.slug == "csrf_failed"
