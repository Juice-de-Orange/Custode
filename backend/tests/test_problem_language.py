"""Problem responses speak English (`title`/`detail`, RFC 9457).

The web client branches on the slug and translates through its own catalogs, so `title` and
`detail` are what everyone *else* reads: API users, scripts, the operator in the logs. They are
English. The slugs stay exactly as they are — they are the contract (`docs/errors.md`).

Static (AST over ``app/``) plus a handful of real requests against the handlers. No Docker.
"""

from __future__ import annotations

import ast
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.kernel.auth.passwords import MAX_PASSWORD_LENGTH, password_too_weak
from app.main import create_app

APP_DIR = Path(__file__).resolve().parents[1] / "app"

#: Umlauts, ß, or a German function word. Crude on purpose: the titles are short sentences, and
#: every German one in the tree used to trip at least one of these.
_GERMAN = re.compile(
    r"[äöüÄÖÜß]|\b(?:nicht|kein|keine|ungültig|bereits|bitte|zwischenzeitlich|gefunden|"
    r"erforderlich|abgelaufen|der|das|ist|und|oder|für|mit|nur|noch|dein|deine|du|zu|vom|"
    r"Fehler|Eingabe|Sitzung|Haushalt|Konto|Passwort)\b",
    re.IGNORECASE,
)


def _texts(node: ast.expr) -> list[str]:
    """The literal text a ``title=``/``detail=`` expression can produce (both branches of a
    conditional, the constant parts of an f-string)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant)]
    if isinstance(node, ast.IfExp):
        return _texts(node.body) + _texts(node.orelse)
    if isinstance(node, ast.BoolOp):
        return [t for v in node.values for t in _texts(v)]
    return []


def _problem_texts() -> list[tuple[str, int, str]]:
    """Every literal ``title``/``detail`` of a call that builds a problem: any call with a
    ``slug=`` keyword (``ProblemException``, its subclasses' ``super().__init__``) and the kernel
    factory ``_problem``."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            kwargs = {kw.arg for kw in node.keywords}
            if "slug" not in kwargs and name != "_problem":
                continue
            for kw in node.keywords:
                if kw.arg in ("title", "detail"):
                    for text in _texts(kw.value):
                        found.append((str(path.relative_to(APP_DIR)), node.lineno, text))
    return found


def test_the_scan_sees_the_problem_calls() -> None:
    """Guard against a scan that silently finds nothing and therefore passes."""
    assert len(_problem_texts()) > 250


def test_problem_titles_and_details_are_english() -> None:
    german = [
        f"{path}:{line}: {text}" for path, line, text in _problem_texts() if _GERMAN.search(text)
    ]
    assert german == [], "German problem title/detail:\n" + "\n".join(german)


def test_password_policy_reasons_are_english() -> None:
    """``password_too_weak`` feeds the ``detail`` of ``weak_password``."""
    for password in ("short", "x" * (MAX_PASSWORD_LENGTH + 1)):
        reason = password_too_weak(password)
        assert reason is not None
        assert not _GERMAN.search(reason), reason


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app()

    @app.get("/__test__/boom")
    async def _boom() -> None:
        raise RuntimeError("boom")

    @app.get("/__test__/items/{item_id}")
    async def _item(item_id: int) -> int:
        return item_id

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_handler_problems_are_english(api: AsyncClient) -> None:
    """The three problems the kernel builds itself, without a ``ProblemException``."""
    validation = (await api.get("/__test__/items/not-a-number")).json()
    assert validation["type"].endswith("#validation")
    assert validation["title"] == "Invalid input"
    assert validation["detail"] == "Validation failed."

    internal = (await api.get("/__test__/boom")).json()
    assert internal["type"].endswith("#internal")
    assert internal["title"] == "Unexpected error"
    assert not _GERMAN.search(internal["detail"])

    missing = (await api.get("/__test__/nowhere")).json()
    assert missing["type"].endswith("#not_found")
    assert missing["title"] == "Not Found"


async def test_register_validation_message_is_english(api: AsyncClient) -> None:
    """A schema validator's message travels inside the ``validation`` problem (``errors``)."""
    resp = await api.post(
        "/v1/auth/register",
        json={"email": "no-at-sign", "password": "x" * 12, "display_name": "X"},
    )
    assert resp.status_code == 422
    messages = [error["msg"] for error in resp.json()["errors"]]
    assert any("Invalid e-mail address." in msg for msg in messages), messages
