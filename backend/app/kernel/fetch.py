"""SSRF-guarded outbound HTTP for user-supplied URLs — the recipe importer fetches arbitrary URLs,
which KONZEPT §8 calls "die exponierteste Stelle des Backends". Guarantees:

- only ``http``/``https`` (no ``file://``, ``gopher://``, …);
- every resolved A/AAAA address must be public — blocks private / loopback / link-local (incl. the
  cloud-metadata 169.254.169.254) / multicast / reserved / unspecified ranges, including when a
  hostname *resolves* to one (DNS-pinning intent: we trust the resolved addresses, not the name);
- redirects are followed manually, capped, and the target is re-validated on every hop;
- with credentials attached, redirects are additionally restricted to the SAME origin — no
  credential may travel to a foreign host, Basic tuple and Bearer token alike (CalDAV, P9-S3).
  Corollary: pass credentials via ``auth=``/``bearer=``, NEVER by hand in ``headers`` — the lock
  only sees what it is given (ADR-0030 addendum);
- response size and total time are bounded.

Two calling conventions share one engine: ``safe_fetch`` keeps the recipe importer's request-path
contract (generic ``ProblemException``s that never echo the resolved address), while
``safe_request`` serves worker-side callers (CalDAV sync) with plain ``FetchError`` exceptions and
an arbitrary method/body/auth. Residual note: a sub-TTL DNS-rebind between our lookup and httpx's
own is not closed here (connection-level IP-pinning is a documented hardening follow-up,
ADR-0030); every resolved record is checked, which blocks the practical vectors."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.kernel.http.problem import ProblemException

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 3
MAX_BYTES = 2 * 1024 * 1024  # 2 MiB — recipe pages are HTML, not downloads
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_USER_AGENT = "CustodeRecipeImport/1.0"


class FetchError(Exception):
    """Base for guarded-fetch failures. Deliberately carries no target details — the URL and the
    resolved address may be attacker-influenced and must never leak into logs or responses."""


class FetchBlockedError(FetchError):
    """The target is not allowed: bad scheme, missing host, internal address, credential-bearing
    redirect to a foreign origin, or a redirect without a Location."""


class FetchFailedError(FetchError):
    """The target could not be fetched: DNS failure, connect/read error, or timeout."""


class FetchTooLargeError(FetchError):
    """The response exceeded the byte cap."""


class FetchTooManyRedirectsError(FetchError):
    """The redirect chain exceeded ``MAX_REDIRECTS``."""


def _blocked() -> ProblemException:
    # One opaque slug for every SSRF rejection — never leak the resolved IP or which check tripped.
    return ProblemException(slug="import_url_blocked", title="URL nicht erlaubt", status=400)


def _unreachable() -> ProblemException:
    return ProblemException(slug="import_fetch_failed", title="Seite nicht erreichbar", status=400)


def is_public_ip(raw_ip: str) -> bool:
    """True only for globally routable unicast addresses. Everything internal is rejected."""
    ip = ipaddress.ip_address(raw_ip)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _assert_public_host_raw(host: str) -> None:
    """Resolve *host* and require EVERY resolved address to be public (``FetchError`` shape)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchFailedError() from exc
    if not infos:
        raise FetchBlockedError()
    for info in infos:
        if not is_public_ip(str(info[4][0])):
            raise FetchBlockedError()


def assert_public_host(host: str) -> None:
    """Resolve *host* and require EVERY resolved address to be public. Raises ``import_url_blocked``
    if any address is internal, ``import_fetch_failed`` if the name does not resolve."""
    try:
        _assert_public_host_raw(host)
    except FetchBlockedError as exc:
        raise _blocked() from exc
    except FetchFailedError as exc:
        raise _unreachable() from exc


async def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None,
    content: bytes | None,
    auth: tuple[str, str] | None,
    bearer: str | None,
    max_bytes: int,
    allow_private: bool,
    user_agent: str,
    http_timeout: httpx.Timeout,
) -> tuple[int, str, str, dict[str, str]]:
    """The shared engine: manual, re-validated redirects + capped streaming read. Returns
    ``(status_code, final_url, body_text, response_headers)`` — non-2xx statuses are returned,
    not raised (the caller interprets them). Response headers are server-controlled: never log
    them. Raises the ``FetchError`` family for guard/transport failures."""
    current = url
    origin: tuple[str, str, int | None] | None = None  # locked once a credential is in play
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=http_timeout,
        headers={
            "User-Agent": user_agent,
            **({"Authorization": f"Bearer {bearer}"} if bearer else {}),
            **(headers or {}),
        },
        auth=auth,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ALLOWED_SCHEMES:
                raise FetchBlockedError()
            host = parsed.hostname
            if not host:
                raise FetchBlockedError()
            if not allow_private:
                _assert_public_host_raw(host)
            # A Bearer token counts as a credential exactly like Basic auth — more so, since it
            # is pure bearer authority with no origin binding of its own. Gating this on ``auth``
            # alone would have let an OAuth token follow a redirect to a foreign host.
            if auth is not None or bearer is not None:
                # Credentials must never follow a redirect to a foreign origin.
                this_origin = (parsed.scheme, host, parsed.port)
                if origin is None:
                    origin = this_origin
                elif this_origin != origin:
                    raise FetchBlockedError()

            try:
                async with client.stream(method, current, content=content) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchBlockedError()
                        current = urljoin(current, location)
                        continue
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchTooLargeError()
                        chunks.append(chunk)
                    encoding = resp.encoding or "utf-8"
                    body = b"".join(chunks).decode(encoding, errors="replace")
                    return resp.status_code, str(resp.url), body, dict(resp.headers)
            except httpx.HTTPError as exc:
                raise FetchFailedError() from exc
    raise FetchTooManyRedirectsError()


async def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    auth: tuple[str, str] | None = None,
    bearer: str | None = None,
    max_bytes: int = MAX_BYTES,
    allow_private: bool = False,
    user_agent: str = "Custode/1.0",
    http_timeout: httpx.Timeout = TIMEOUT,
) -> tuple[int, str, dict[str, str]]:
    """Arbitrary-method request under the same SSRF protection as ``safe_fetch`` (P9-S3/S4:
    CalDAV REPORT/GET/PUT/DELETE with body + Basic auth; ``bearer`` for OAuth-authenticated
    collections such as Google). ``auth`` and ``bearer`` are equally origin-locking: a credential
    of either form must never follow a redirect to a foreign host. Returns
    ``(status_code, body_text, response_headers)`` — evaluating the status is the caller's job;
    the headers carry e.g. the ETag of a PUT (server-controlled: never log them). Raises the
    ``FetchError`` family (worker-friendly, no HTTP semantics). ``allow_private`` skips only the
    public-address check (dev/tests/self-hosted targets); scheme/host validation and all other
    caps still apply."""
    status, _final, body, resp_headers = await _request(
        method,
        url,
        headers=headers,
        content=content,
        auth=auth,
        bearer=bearer,
        max_bytes=max_bytes,
        allow_private=allow_private,
        user_agent=user_agent,
        http_timeout=http_timeout,
    )
    return status, body, resp_headers


async def safe_fetch(url: str) -> tuple[str, str]:
    """GET *url* under SSRF protection. Returns ``(final_url, body_text)``. Raises a 400
    ``ProblemException`` on a blocked target, a fetch failure, too many redirects, or an
    oversized response."""
    try:
        status, final_url, body, _headers = await _request(
            "GET",
            url,
            headers=None,
            content=None,
            auth=None,
            bearer=None,
            max_bytes=MAX_BYTES,
            allow_private=False,
            user_agent=_USER_AGENT,
            http_timeout=TIMEOUT,
        )
    except FetchTooLargeError as exc:
        raise ProblemException(slug="import_too_large", title="Seite zu groß", status=400) from exc
    except FetchTooManyRedirectsError as exc:
        raise ProblemException(
            slug="import_too_many_redirects", title="Zu viele Weiterleitungen", status=400
        ) from exc
    except FetchBlockedError as exc:
        raise _blocked() from exc
    except FetchFailedError as exc:
        raise _unreachable() from exc
    if status >= 400:
        # raise_for_status() semantics of the old implementation: any error status is a fetch
        # failure for the importer.
        raise _unreachable()
    return final_url, body
