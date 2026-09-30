"""RFC 9457 application/problem+json (ADR-009). Clients branch on ``type``,
never on message strings. Every response carries a ``reference`` (short code
derived from request_id) for support/trace correlation (ARCHITECTURE §12)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger

PROBLEM_BASE = "https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#"

_STATUS_SLUGS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    412: "conflict_version",
    429: "rate_limited",
}


class ProblemException(Exception):
    """Raise inside services/routers to emit a typed problem response."""

    def __init__(
        self,
        *,
        slug: str,
        title: str,
        status: int,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.slug = slug
        self.title = title
        self.status = status
        self.detail = detail
        self.extra = extra or {}
        super().__init__(title)


def _reference(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _problem(
    *,
    status: int,
    slug: str,
    title: str,
    detail: str | None = None,
    reference: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": PROBLEM_BASE + slug, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if reference is not None:
        body["reference"] = reference
    if extra:
        body.update(extra)
    response = JSONResponse(status_code=status, content=body, media_type="application/problem+json")
    if reference is not None:
        # Der Header wird sonst von ``RequestContextMiddleware`` gesetzt — die aber sieht einen
        # unerwarteten Fehler nie: einen Handler für ``Exception`` fährt Starlette in der
        # ``ServerErrorMiddleware``, und die sitzt **äußerhalb** unserer Middleware. Ohne diese
        # Zeile trüge ausgerechnet die 500 den Code nur im Body und nicht im Header.
        response.headers["X-Request-ID"] = reference
    return response


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemException)
    async def _on_problem(request: Request, exc: ProblemException) -> JSONResponse:
        return _problem(
            status=exc.status,
            slug=exc.slug,
            title=exc.title,
            detail=exc.detail,
            reference=_reference(request),
            extra=exc.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            status=422,
            slug="validation",
            title="Eingabe ungültig",
            detail="Validierung fehlgeschlagen.",
            reference=_reference(request),
            extra={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = _STATUS_SLUGS.get(exc.status_code, "error")
        detail = str(exc.detail) if exc.detail else None
        return _problem(
            status=exc.status_code,
            slug=slug,
            title=detail or "Fehler",
            reference=_reference(request),
        )

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """The last resort — and until 11-A2 it did not exist.

        An unhandled error fell through to Starlette's ``ServerErrorMiddleware`` and left as
        ``text/plain`` "Internal Server Error": no ``type``, no ``reference``, not even
        ``problem+json``. ``docs/errors.md`` promises the opposite twice ("jeder 5xx trägt einen
        ``reference``-Code"), and ARCHITECTURE §12 builds the whole five-minute-debuggability claim
        on that code being on screen. The one moment a user most needs a code to quote is the one
        moment they had none.

        The body carries **only** the code. Not the exception type, not the message: an unexpected
        error is exactly where an internal detail (a constraint name, a row, a path) would leak,
        and the operator can resolve the reference to the full traceback in the logs.
        """
        log = get_logger("http.unhandled")
        reference = _reference(request)
        # exc_info via ``exception``: the traceback belongs in the log, never in the response.
        log.exception("unhandled_exception", reference=reference, route=request.url.path)
        return _problem(
            status=500,
            slug="internal",
            title="Unerwarteter Fehler",
            detail="Bitte versuche es erneut. Nenne beim Melden den Referenzcode.",
            reference=reference,
        )
