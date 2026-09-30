"""Pure feedback→issue mapping (ADR-0076). No DB, no network — unit-testable in isolation (mirrors
capture/enrich.py). ``build_issue`` turns a stored feedback row into the title/body/labels of an
issue; the actual POST is the injected ``IssueTrackerPort``. The message is user content and goes to
the operator's configured tracker on purpose — but it is NEVER logged (root CLAUDE.md)."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.feedback.models import Feedback

# Feedback categories (bug/idea/praise/other) → a conventional GitHub issue label. Everything also
# gets the "feedback" label so forwarded issues are filterable.
_CATEGORY_LABELS: dict[str, str] = {
    "bug": "bug",
    "idea": "enhancement",
    "praise": "praise",
    "other": "question",
}
_TITLE_MAX = 72


@dataclass(frozen=True)
class IssueDraft:
    title: str
    body: str
    labels: list[str]


def build_issue(feedback: Feedback) -> IssueDraft:
    category = feedback.category
    stripped = (feedback.message or "").strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    snippet = first_line[:_TITLE_MAX] + ("…" if len(first_line) > _TITLE_MAX else "")
    title = f"[{category}] {snippet}" if snippet else f"[{category}] Feedback"

    body_lines = [
        f"**Kategorie:** {category}",
        f"**Route:** {feedback.route or '—'}",
        f"**Fehler-Referenz:** {feedback.error_ref or '—'}",
        f"**Feedback-ID:** {feedback.id}",
        f"**Haushalt:** {feedback.household_id}",
    ]
    if feedback.diagnostics:
        body_lines.append("**Diagnose-Anhang:** vorhanden (in der Betreiber-Inbox einsehbar)")
    body_lines += ["", stripped, "", "_Automatisch aus dem In-App-Feedback weitergeleitet._"]

    labels = ["feedback"]
    mapped = _CATEGORY_LABELS.get(category)
    if mapped:
        labels.append(mapped)
    return IssueDraft(title=title, body="\n".join(body_lines), labels=labels)
