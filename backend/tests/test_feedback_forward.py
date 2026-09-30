"""Feedback → issue-tracker forwarding (ADR-0076). Pure tests — no Docker/DB/network:

* Null path (default): the Null adapter accepts as a no-op (forwarding off).
* Real path: the GitHub adapter POSTs a well-formed issue and degrades gracefully on failure.
* Factory selection: token+repo -> GitHub, else Null (inert by default).
* Pure mapping (build_issue) and the handler's swallow-all forward step.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.github.issues import GitHubIssueTracker
from app.adapters.null import NullIssueTracker
from app.issue_factory import build_issue_tracker
from app.kernel.events.envelope import EventEnvelope
from app.modules.feedback.forward import IssueDraft, build_issue
from app.modules.feedback.handlers import _forward_draft, on_feedback_created
from app.modules.feedback.models import Feedback
from app.settings import Settings


def _feedback(**kw: object) -> Feedback:
    fb = Feedback(
        household_id=kw.get("household_id", uuid.uuid4()),
        author_id=uuid.uuid4(),
        category=kw.get("category", "bug"),
        message=kw.get("message", "Es kracht beim Speichern."),
        error_ref=kw.get("error_ref"),
        route=kw.get("route"),
        diagnostics=kw.get("diagnostics"),
    )
    fb.id = kw.get("id", uuid.uuid4())  # server-generated in prod; set here (no DB)
    return fb


# ------------------------------------------------------------------ Null path (default)


async def test_null_issue_tracker_is_noop() -> None:
    assert await NullIssueTracker().forward(title="x", body="y", labels=["feedback"]) is True


def test_factory_selects_null_without_config() -> None:
    # _env_file=None keeps the test hermetic (no ambient .env / CUSTODE_* leaking in).
    tracker = build_issue_tracker(Settings(_env_file=None, github_token=None, github_repo=None))
    assert isinstance(tracker, NullIssueTracker)


def test_factory_selects_github_when_configured() -> None:
    tracker = build_issue_tracker(
        Settings(_env_file=None, github_token="tok", github_repo="acme/app")
    )
    assert isinstance(tracker, GitHubIssueTracker)


# ------------------------------------------------------------------ real path (GitHub)


_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before monkeypatching (avoid self-recursion)


def _github(monkeypatch: pytest.MonkeyPatch, handler: object) -> GitHubIssueTracker:
    monkeypatch.setattr(
        "app.adapters.github.issues.httpx.AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)),
    )
    # Pin every github_* field (incl. api_url) + drop .env so the URL assertion is env-independent.
    return GitHubIssueTracker(
        Settings(
            _env_file=None,
            github_token="tok",
            github_repo="acme/app",
            github_api_url="https://api.github.com",
        )
    )


async def test_github_forward_posts_wellformed_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["api_version"] = request.headers.get("x-github-api-version")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"number": 7})

    ok = await _github(monkeypatch, handler).forward(
        title="[bug] kaputt", body="Details", labels=["feedback", "bug"]
    )
    assert ok is True
    assert seen["url"] == "https://api.github.com/repos/acme/app/issues"
    assert seen["auth"] == "Bearer tok"
    assert seen["api_version"] == "2022-11-28"
    assert seen["body"] == {
        "title": "[bug] kaputt",
        "body": "Details",
        "labels": ["feedback", "bug"],
    }


async def test_github_forward_degrades_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = _github(monkeypatch, lambda request: httpx.Response(500))
    assert await tracker.forward(title="t", body="b", labels=[]) is False


async def test_github_forward_degrades_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await _github(monkeypatch, boom).forward(title="t", body="b", labels=[]) is False


# ------------------------------------------------------------------ pure mapping


def test_build_issue_maps_category_route_and_labels() -> None:
    draft = build_issue(
        _feedback(category="idea", message="Bitte Dark-Mode", route="/today", error_ref="CUS-1")
    )
    assert draft.title.startswith("[idea] Bitte Dark-Mode")
    assert draft.labels == ["feedback", "enhancement"]
    assert "**Route:** /today" in draft.body
    assert "**Fehler-Referenz:** CUS-1" in draft.body
    assert "Bitte Dark-Mode" in draft.body


def test_build_issue_handles_blank_and_overlong_message() -> None:
    blank = build_issue(_feedback(category="bug", message="   "))
    assert blank.title == "[bug] Feedback"
    long = build_issue(_feedback(message="x" * 200))
    assert long.title.endswith("…") and len(long.title) < 90


def test_build_issue_notes_optional_diagnostics() -> None:
    with_diag = build_issue(_feedback(diagnostics={"app_version": "1.0"}))
    assert "Diagnose-Anhang" in with_diag.body
    without = build_issue(_feedback(diagnostics=None))
    assert "Diagnose-Anhang" not in without.body


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("bug", ["feedback", "bug"]),
        ("idea", ["feedback", "enhancement"]),
        ("praise", ["feedback", "praise"]),
        ("other", ["feedback", "question"]),
        ("weird", ["feedback"]),  # unknown category -> only the base label
    ],
)
def test_build_issue_labels_per_category(category: str, expected: list[str]) -> None:
    assert build_issue(_feedback(category=category, message="x")).labels == expected


# ------------------------------------------------------------------ handler forward step (graceful)


async def test_forward_draft_calls_tracker() -> None:
    calls: list[tuple[str, str, list[str]]] = []

    class Fake:
        async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
            calls.append((title, body, labels))
            return True

    await _forward_draft(Fake(), IssueDraft(title="T", body="B", labels=["feedback"]))
    assert calls == [("T", "B", ["feedback"])]


async def test_forward_draft_swallows_adapter_errors() -> None:
    class Boom:
        async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
            raise RuntimeError("tracker down")

    # Must not raise — forwarding is best-effort and never breaks the worker.
    await _forward_draft(Boom(), IssueDraft(title="T", body="B", labels=[]))


async def test_handler_ignores_event_without_id() -> None:
    """A feedback.created without an id in the payload is skipped before any DB/forward work."""
    called = False

    class Fake:
        async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
            nonlocal called
            called = True
            return True

    event = EventEnvelope(
        type="feedback.created",
        household_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload={},
    )
    await on_feedback_created(event, Fake())
    assert called is False


class _Capture:
    def __init__(self) -> None:
        self.titles: list[str] = []

    async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
        self.titles.append(title)
        return True


def _patch_db(monkeypatch: pytest.MonkeyPatch, feedback: Feedback | None) -> None:
    """Stub the handler's DB boundary (scoped_session + service.get_feedback) so its orchestration —
    id parse, load, build_issue on the row, forward — is exercised without Postgres. The real query
    is a thin session.scalars().first() (RLS covered by test_feedback_rls.py)."""

    @asynccontextmanager
    async def fake_scoped(*, household_id: uuid.UUID, user_id: str):  # type: ignore[no-untyped-def]
        yield object()

    async def fake_get(session: object, *, feedback_id: uuid.UUID) -> Feedback | None:
        return feedback

    monkeypatch.setattr("app.modules.feedback.handlers.scoped_session", fake_scoped)
    monkeypatch.setattr("app.modules.feedback.service.get_feedback", fake_get)


async def test_handler_loads_and_forwards_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    feedback = _feedback(category="bug", message="Absturz beim Speichern", id=uuid.uuid4())
    _patch_db(monkeypatch, feedback)
    tracker = _Capture()
    event = EventEnvelope(
        type="feedback.created",
        household_id=feedback.household_id,
        occurred_at=datetime.now(UTC),
        payload={"id": str(feedback.id)},
    )
    await on_feedback_created(event, tracker)
    assert tracker.titles == ["[bug] Absturz beim Speichern"]


async def test_handler_skips_when_row_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, None)  # e.g. already soft-deleted / wrong household under RLS
    tracker = _Capture()
    event = EventEnvelope(
        type="feedback.created",
        household_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload={"id": str(uuid.uuid4())},
    )
    await on_feedback_created(event, tracker)
    assert tracker.titles == []
