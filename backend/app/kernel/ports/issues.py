from __future__ import annotations

from typing import Protocol


class IssueTrackerPort(Protocol):
    """Outbound forwarding of a piece of user feedback to an external issue tracker (ADR-0076).

    Graceful Enhancement: the Null implementation is a no-op, so the app (in-app feedback + the
    operator inbox) works fully without any tracker configured. A real adapter (GitHub Issues)
    is best-effort — a forwarding failure must never break feedback submission — and returns
    ``False`` rather than raising. Lives in the kernel so modules depend only on ``kernel/*``;
    the concrete adapter is selected at the composition root (``app/issue_factory.py``,
    ``app/worker.py``) — import-linter forbids ``modules``/``kernel`` → ``adapters``.
    """

    async def forward(self, *, title: str, body: str, labels: list[str]) -> bool: ...
