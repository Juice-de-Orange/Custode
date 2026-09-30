"""Unit tests for the SSRF guard (kernel/fetch.py). Pure logic + monkeypatched DNS — no Docker and
no real network, so these run everywhere (and actually exercise the security decisions locally)."""

from __future__ import annotations

import socket

import pytest

from app.kernel.fetch import assert_public_host, is_public_ip, safe_fetch
from app.kernel.http.problem import ProblemException


@pytest.mark.parametrize(
    "ip",
    ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"],
)
def test_public_ips_pass(ip: str) -> None:
    assert is_public_ip(ip) is True


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",  # private
        "172.16.5.4",  # private
        "192.168.1.1",  # private
        "127.0.0.1",  # loopback
        "169.254.169.254",  # link-local — cloud metadata endpoint
        "0.0.0.0",  # unspecified  # noqa: S104
        "224.0.0.1",  # multicast
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local (private)
    ],
)
def test_internal_ips_blocked(ip: str) -> None:
    assert is_public_ip(ip) is False


def _patch_dns(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET

    def fake(host: str, *args: object, **kwargs: object) -> list[object]:
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("app.kernel.fetch.socket.getaddrinfo", fake)


def test_assert_public_host_blocks_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, "10.1.2.3")
    with pytest.raises(ProblemException) as exc:
        assert_public_host("intranet.example")
    assert exc.value.slug == "import_url_blocked"


def test_assert_public_host_allows_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, "93.184.216.34")
    assert_public_host("example.com")  # does not raise


def test_assert_public_host_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror("name does not resolve")

    monkeypatch.setattr("app.kernel.fetch.socket.getaddrinfo", boom)
    with pytest.raises(ProblemException) as exc:
        assert_public_host("nx.invalid")
    assert exc.value.slug == "import_fetch_failed"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://h/1"])
async def test_safe_fetch_blocks_scheme(url: str) -> None:
    with pytest.raises(ProblemException) as exc:
        await safe_fetch(url)
    assert exc.value.slug == "import_url_blocked"


async def test_safe_fetch_blocks_dns_to_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # A hostname that resolves to the cloud-metadata link-local address must be refused before
    # any connection is attempted.
    _patch_dns(monkeypatch, "169.254.169.254")
    with pytest.raises(ProblemException) as exc:
        await safe_fetch("http://metadata.evil.test/latest/meta-data/")
    assert exc.value.slug == "import_url_blocked"


# --- safe_request (P9-S3, ADR-0079) -------------------------------------------

import asyncio

from app.kernel.fetch import (
    FetchBlockedError,
    FetchFailedError,
    safe_request,
)


async def test_safe_request_blocks_private_target(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, "10.1.2.3")
    with pytest.raises(FetchBlockedError):
        await safe_request("REPORT", "http://intranet.example/dav/")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x"])
async def test_safe_request_blocks_scheme(url: str) -> None:
    with pytest.raises(FetchBlockedError):
        await safe_request("REPORT", url, allow_private=True)


async def test_allow_private_reaches_the_connection_stage() -> None:
    # A loopback target passes the guard with allow_private=True and then fails at connect
    # (closed port) — FetchFailedError, not FetchBlockedError, proves the guard stood down.
    with pytest.raises(FetchFailedError):
        await safe_request("GET", "http://127.0.0.1:59999/", allow_private=True)


async def _one_shot_redirect_server(location: str) -> tuple[asyncio.Server, int]:
    """Minimal HTTP server answering every request with a 302 to ``location``."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()  # request line is enough
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: " + location.encode() + b"\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def test_credentialed_redirect_to_foreign_origin_is_blocked() -> None:
    # Basic auth must never travel to another origin: a redirect to a different host/port with
    # auth attached is refused (same-origin lock), even though the target itself would be allowed.
    server, port = await _one_shot_redirect_server("http://127.0.0.1:59998/other/")
    try:
        with pytest.raises(FetchBlockedError):
            await safe_request(
                "GET",
                f"http://127.0.0.1:{port}/dav/",
                auth=("user", "pass"),
                allow_private=True,
            )
    finally:
        server.close()
        await server.wait_closed()


async def test_bearer_redirect_to_foreign_origin_is_blocked() -> None:
    """A Bearer token is pure inhaber authority — no origin binding of its own, so leaking one is
    strictly worse than leaking Basic auth. Gating the origin lock on ``auth`` alone (as it was
    before P9's Google work) would have let an OAuth token follow a redirect to any host."""
    server, port = await _one_shot_redirect_server("http://127.0.0.1:59998/other/")
    try:
        with pytest.raises(FetchBlockedError):
            await safe_request(
                "GET",
                f"http://127.0.0.1:{port}/dav/",
                bearer="ya29.a0-secret-access-token",
                allow_private=True,
            )
    finally:
        server.close()
        await server.wait_closed()


async def test_bearer_is_sent_as_an_authorization_header() -> None:
    """The header form the CalDAV/Google path relies on."""
    seen: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            seen.append(line.decode().strip())
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        status, body, _ = await safe_request(
            "GET", f"http://127.0.0.1:{port}/dav/", bearer="tok-123", allow_private=True
        )
        assert status == 200
        assert body == "ok"
        assert any(h.lower() == "authorization: bearer tok-123" for h in seen)
    finally:
        server.close()
        await server.wait_closed()


async def test_anonymous_redirect_may_change_origin() -> None:
    # Without credentials the origin lock does not apply — the hop is re-validated and then
    # fails at connect on the (closed) target port: FetchFailedError, not FetchBlockedError.
    server, port = await _one_shot_redirect_server("http://127.0.0.1:59998/other/")
    try:
        with pytest.raises(FetchFailedError):
            await safe_request("GET", f"http://127.0.0.1:{port}/dav/", allow_private=True)
    finally:
        server.close()
        await server.wait_closed()


async def _one_shot_etag_server() -> tuple[asyncio.Server, int]:
    """Minimal HTTP server answering every request with 200 + an ETag header."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(
            b'HTTP/1.1 200 OK\r\nETag: "v42"\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok'
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def test_safe_request_returns_response_headers() -> None:
    # P9-S4: the CalDAV write-back reads the PUT response's ETag — headers must round-trip.
    server, port = await _one_shot_etag_server()
    try:
        status, body, headers = await safe_request(
            "GET", f"http://127.0.0.1:{port}/x", allow_private=True
        )
    finally:
        server.close()
        await server.wait_closed()
    assert status == 200
    assert body == "ok"
    assert headers.get("etag") == '"v42"'
