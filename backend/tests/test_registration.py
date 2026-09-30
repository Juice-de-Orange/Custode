"""Registration policy tests (no DB): a weak or breached password is rejected
*before* any DB access, so these run locally. The DB paths (create, duplicate
e-mail) live in test_registration_db.py (Testcontainers)."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.kernel.http.problem import ProblemException
from app.modules.accounts.service import register_user


def _hibp_match(password: str) -> httpx.AsyncClient:
    suffix = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()[5:]
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=f"{suffix}:9001"))
    )


async def test_register_rejects_weak_password() -> None:
    with pytest.raises(ProblemException) as ei:
        await register_user(email="a@b.de", password="kurz", display_name="A")
    assert ei.value.slug == "weak_password"


async def test_register_rejects_pwned_password() -> None:
    pw = "correct-horse-staple-1"
    async with _hibp_match(pw) as client:
        with pytest.raises(ProblemException) as ei:
            await register_user(email="a@b.de", password=pw, display_name="A", pwned_client=client)
    assert ei.value.slug == "pwned_password"
