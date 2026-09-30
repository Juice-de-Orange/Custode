"""HTTP conditional-request helpers (RFC 9110). If-Match optimistic concurrency: the client echoes
the ETag it last read (= the row ``version``); a stale value is a 412, a missing header a 428.
Shared by every PATCH that guards a versioned row (accounts profile, recipes, …)."""

from __future__ import annotations

from app.kernel.http.problem import ProblemException


def parse_if_match(raw: str | None) -> int:
    """Parse an If-Match header into the expected ``version``. Missing -> 428 (the client must send
    the ETag it read); malformed -> 412. Tolerates quotes and a weak-validator ``W/`` prefix."""
    if not raw:
        raise ProblemException(
            slug="precondition_required", title="If-Match erforderlich", status=428
        )
    try:
        return int(raw.strip().removeprefix("W/").strip().strip('"'))
    except ValueError as exc:
        raise ProblemException(
            slug="precondition_failed", title="If-Match ungültig", status=412
        ) from exc
