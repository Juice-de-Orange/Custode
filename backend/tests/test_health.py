from __future__ import annotations

from httpx import AsyncClient


async def test_healthz_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_healthz_head_not_500(client: AsyncClient) -> None:
    # Regression: HEAD probes (uptime checks, Cloudflare) must not 500 — the otel
    # FastAPI instrumentation crashed on HEAD until /healthz was excluded.
    resp = await client.head("/healthz")
    assert resp.status_code == 200


async def test_readyz_shape(client: AsyncClient) -> None:
    # Without infra (local, no Docker) this is 503/degraded; the shape is stable.
    resp = await client.get("/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert "checks" in body
    assert set(body["checks"]) == {"database", "redis"}
