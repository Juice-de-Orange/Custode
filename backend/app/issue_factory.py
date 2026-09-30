"""Issue-tracker adapter factory (ADR-0076). Used by the worker composition root
(``app/worker.py``) to pick the adapter from settings: the real GitHub adapter when a token AND a
repo are configured, else the Null adapter (forwarding off — feedback still lands in-app and in the
operator inbox). INERT by default: no token/repo -> Null -> no outbound call, no secret in repo."""

from __future__ import annotations

from app.adapters.github.issues import GitHubIssueTracker
from app.adapters.null import NullIssueTracker
from app.kernel.ports.issues import IssueTrackerPort
from app.settings import Settings


def build_issue_tracker(settings: Settings) -> IssueTrackerPort:
    if settings.github_token and settings.github_repo:
        return GitHubIssueTracker(settings)
    return NullIssueTracker()
