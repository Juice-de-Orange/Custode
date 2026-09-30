"""GitHub Issues adapter (ADR-0076). Implements ``IssueTrackerPort`` by opening an issue in a
configured repository via the REST API. Best-effort Graceful Enhancement: any failure (network,
timeout, 4xx/5xx) degrades to ``False`` and is logged by failure class only — it never raises into
the worker, so a forwarding hiccup can never break feedback submission. The host is fixed
(``api.github.com``) and the repo comes from server config (no user-supplied URL -> not the SSRF
surface guarded by ``kernel/fetch``). The token is read from env, never the repo (settings)."""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.github")


class GitHubIssueTracker:
    def __init__(self, settings: Settings) -> None:
        # The factory only builds this when both are set; guard (and narrow the type) defensively.
        if settings.github_token is None or settings.github_repo is None:
            raise ValueError("GitHubIssueTracker requires github_token and github_repo")
        self._token = settings.github_token
        self._repo = settings.github_repo.strip("/")  # "owner/repo"
        self._api = settings.github_api_url.rstrip("/")
        self._timeout = settings.github_timeout_s

    async def forward(self, *, title: str, body: str, labels: list[str]) -> bool:
        """POST a new issue. Returns True on 2xx, else False (never raises)."""
        url = f"{self._api}/repos/{self._repo}/issues"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url, headers=headers, json={"title": title, "body": body, "labels": labels}
                )
                resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            # Log the failure class only — never the title/body (user content, PII).
            _log.warning("github_issue_forward_failed", error=type(exc).__name__)
            return False
