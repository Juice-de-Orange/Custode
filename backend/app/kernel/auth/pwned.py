"""Pwned-Passwords check via HIBP k-anonymity (KONZEPT §8). Only the first 5 hex
chars of the password's SHA-1 leave the process — the full password never does.

Graceful (Null-Adapter principle, CLAUDE.md): returns ``None`` when the service is
unreachable, so registration still works without it; the caller logs and proceeds.
A positive count means the password appeared in a breach and must be rejected."""

from __future__ import annotations

import hashlib

import httpx

_HIBP_RANGE = "https://api.pwnedpasswords.com/range/"


async def pwned_count(password: str, *, client: httpx.AsyncClient | None = None) -> int | None:
    """How many times ``password`` appears in known breaches, or ``None`` if the
    check could not run (network/timeout/HTTP error)."""
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(3.0))
    try:
        # Add-Padding hides the exact result-set size from a network observer.
        resp = await client.get(f"{_HIBP_RANGE}{prefix}", headers={"Add-Padding": "true"})
        resp.raise_for_status()
        body = resp.text
    except httpx.HTTPError:
        return None
    finally:
        if owns_client:
            await client.aclose()

    for line in body.splitlines():
        line_suffix, _, count = line.partition(":")
        if line_suffix.strip().upper() == suffix:
            try:
                return int(count.strip())
            except ValueError:
                return None
    return 0
