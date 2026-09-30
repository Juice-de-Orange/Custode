"""Subject-rights download routes (Art. 15 Auskunft, Art. 20 Portabilität).

Two routes, and the difference between them is the whole point:

``GET /v1/me/export``          — what is attributable to *me*. Every member may run it, including
                                a child: the right belongs to the person, not to a role.
``GET /v1/household/export``   — the shared household record. **Admin only**, because it contains
                                everything the household holds about everyone in it.

Neither widens what the caller may see. Both run on the caller's own scoped session, so RLS is
the boundary — including the member-scoped Art.-9 tables, which stay invisible to an admin
exporting the household (ADR-0081). There is no maint session anywhere near this code.

The policy lives at the composition root and reaches the route through ``app.state`` — the same
wiring the ports use. The kernel must not name module tables (E2).

Deliberately synchronous. A household at F&F scale produces a file in the low single-digit MB, and
a background job would need an artifact store, a signed download URL and an expiry — three new
moving parts guarding data that is *more* sensitive at rest in a bucket than in one response. The
size cap below is the honest limit: above it the request refuses rather than exhausting memory,
and the job-based variant becomes the documented follow-up.
"""

from __future__ import annotations

import datetime as dt
import functools
import uuid
from collections.abc import Mapping

import anyio.to_thread
from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth.dependencies import AdminPrincipal, CurrentPrincipal, ScopedSession
from app.kernel.export import (
    Attachment,
    ExportPolicy,
    ExportScope,
    ExportTooLarge,
    build_export_archive,
    collect_export,
)
from app.kernel.http.problem import ProblemException
from app.kernel.storage import get_storage

# Fetched per call, not bound at import: structlog caches a module-level logger on first use, and a
# cached logger is invisible to ``capture_logs``. This route promises "counts, never content" in
# its log line — a promise nothing could check would not be worth making.
from app.logging import get_logger

router = APIRouter(tags=["export"])

# The limit bites while COLLECTING, not on the finished file: checking afterwards would mean the
# rows, the JSON and the ZIP were all in memory at once before we say no — the refusal would cost
# more than the answer. 200k rows is far above any household and far below what hurts the process.
_MAX_ROWS = 200_000


def _filename(scope: ExportScope, now: dt.datetime) -> str:
    stamp = now.strftime("%Y-%m-%d")
    return f"custode-export-{scope.value}-{stamp}.zip"


async def _build(
    request: Request,
    session: AsyncSession,
    *,
    scope: ExportScope,
    subject: uuid.UUID | None,
) -> bytes:
    policy: ExportPolicy = request.app.state.export_policy
    excluded: Mapping[str, str] = request.app.state.export_excluded
    attachment_columns: Mapping[str, str] = request.app.state.export_attachment_columns

    try:
        result = await collect_export(
            session, policy=policy, scope=scope, subject_id=subject, max_rows=_MAX_ROWS
        )
    except ExportTooLarge as exc:
        # Counts only — this goes to the operator's log, never a table name or a row.
        get_logger("export").warning("export_too_large", scope=scope.value, rows=exc.rows)
        raise ProblemException(
            slug="export_too_large",
            title="Der Export ist zu groß für den direkten Download",
            status=413,
            detail="Bitte den Betreiber kontaktieren — der Export wird dann bereitgestellt.",
        ) from exc

    storage = get_storage()
    attachments: list[Attachment] = []
    for table, column in attachment_columns.items():
        for row in result.sections.get(table, []):
            key = row.get(column)
            if isinstance(key, str) and key:
                attachments.append(Attachment(key=key, data=storage.get(key), table=table))

    now = dt.datetime.now(dt.UTC)
    # JSON-Serialisierung und Deflate sind CPU-gebunden und dauern bei einem vollen Haushalt
    # Sekunden. In der Ereignisschleife blockierten sie JEDEN anderen Request des Prozesses —
    # ein einzelner Export würde die App für alle anhalten.
    archive = await anyio.to_thread.run_sync(
        functools.partial(
            build_export_archive,
            result,
            policy=policy,
            scope=scope,
            generated_at=now,
            attachments=attachments,
            excluded_tables=excluded,
            storage_available=storage.enabled,
        )
    )
    get_logger("export").info(
        "export_built", scope=scope.value, rows=result.row_count, bytes=len(archive)
    )
    return archive


def _download(archive: bytes, scope: ExportScope) -> Response:
    name = _filename(scope, dt.datetime.now(dt.UTC))
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            # The archive holds personal data; no shared cache may ever keep a copy.
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/v1/me/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "ZIP-Archiv"}},
)
async def export_me(
    request: Request, principal: CurrentPrincipal, session: ScopedSession
) -> Response:
    """Everything attributable to the calling person (Art. 15/20), as a ZIP.

    Any role may do this — the right is the person's. Rows without personal attribution (a shared
    shopping list) are absent and named in the manifest, so the file never implies more than it is.
    """
    archive = await _build(request, session, scope=ExportScope.PERSONAL, subject=principal.user_id)
    return _download(archive, ExportScope.PERSONAL)


@router.get(
    "/v1/household/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "ZIP-Archiv"}},
)
async def export_household(
    request: Request, principal: AdminPrincipal, session: ScopedSession
) -> Response:
    """The shared household record (Art. 20), as a ZIP. Admin only.

    Still not a superset of everything: member-scoped health data belongs to its member, and the
    database keeps it out of this file regardless of the caller's role (ADR-0081).
    """
    # Auch der Haushalts-Export braucht den Aufrufer: die `subject_scoped`-Tabellen bleiben
    # darin auf die eigene Person beschränkt (s. export_policy.py bei `consents`).
    archive = await _build(request, session, scope=ExportScope.HOUSEHOLD, subject=principal.user_id)
    return _download(archive, ExportScope.HOUSEHOLD)
