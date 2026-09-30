"""Liveness/readiness endpoints. /healthz is always ok; /readyz probes deps
with short timeouts and degrades gracefully (no hang when infra is absent)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])


# GET + HEAD: uptime probes (Cloudflare, monitors) commonly use HEAD; without it
# the request fell through to a 405 (and a 500 via the otel HEAD bug, see BUGLOG).
# include_in_schema=False: health/readiness are infra, not a client contract — and
# it avoids a duplicate operationId from the GET+HEAD pair in the generated client.
@router.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(response: Response) -> dict[str, Any]:
    checks = {
        "database": await _check_db(),
        "redis": await _check_redis(),
    }
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


async def _check_db() -> str:
    from sqlalchemy import text

    from app.kernel.db.engine import get_engine

    try:
        async with asyncio.timeout(2):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


async def _check_redis() -> str:
    from app.kernel.redis import get_redis

    try:
        async with asyncio.timeout(2):
            await cast(Awaitable[bool], get_redis().ping())
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"
