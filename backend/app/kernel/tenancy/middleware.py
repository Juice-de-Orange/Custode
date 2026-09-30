"""Request-context middleware: assigns a request reference code (basis for the
user-facing error code, ARCHITECTURE §12) and binds it into structlog."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _reference_code(rid: str) -> str:
    h = rid.replace("-", "").upper()
    return f"CUS-{h[:4]}-{h[4:6]}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        reference = _reference_code(rid)
        request.state.request_id = reference
        structlog.contextvars.bind_contextvars(request_id=reference, route=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = reference
        return response
