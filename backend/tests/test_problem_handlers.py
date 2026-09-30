"""Die vier Fehler-Handler (`kernel/http/problem.py`) — inklusive dem, den es bis 11-A2 nicht gab.

`docs/errors.md` sagt zweimal zu, dass **jeder 5xx einen `reference`-Code trägt**, und
ARCHITECTURE §12 baut das ganze „in unter fünf Minuten auffindbar" darauf, dass dieser Code auf
dem Bildschirm steht. Ohne `@app.exception_handler(Exception)` fiel ein unerwarteter Fehler an
Starlettes `ServerErrorMiddleware` durch und verliess den Server als `text/plain`
„Internal Server Error": kein `type`, kein `reference`, nicht einmal `problem+json`. Der eine
Moment, in dem jemand einen Code am dringendsten bräuchte, war der einzige ohne.

Läuft ohne Docker: die App wird ohne Datenbank hochgezogen, die Testroute wirft von sich aus.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.kernel.http.problem import ProblemException
from app.main import create_app


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app()

    @app.get("/__test__/boom")
    async def _boom() -> None:
        raise RuntimeError("geheimer Innenzustand: constraint uq_users_email on row 42")

    @app.get("/__test__/problem")
    async def _problem() -> None:
        raise ProblemException(slug="teapot", title="Kanne", status=418, detail="kurz und klar")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_an_unhandled_error_answers_problem_json_with_a_reference(
    api: AsyncClient,
) -> None:
    resp = await api.get("/__test__/boom")

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].endswith("#internal")
    assert body["status"] == 500
    # Der Punkt: ohne Code kann der Nutzer nichts melden und der Betreiber nichts finden.
    assert body["reference"], "Ein 5xx ohne Referenzcode ist eine Sackgasse für beide Seiten"
    # Auch im Header — die Kontext-Middleware setzt ihn hier nicht, weil ein Handler für
    # ``Exception`` ausserhalb von ihr laeuft (Starlettes ServerErrorMiddleware).
    assert body["reference"] == resp.headers["X-Request-ID"]


async def test_the_500_body_leaks_neither_the_exception_type_nor_its_message(
    api: AsyncClient,
) -> None:
    """Ein unerwarteter Fehler ist genau die Stelle, an der ein Innendetail entkäme — ein
    Constraint-Name, eine Zeile, ein Pfad. Der Text gehört ins Log, der Code in die Antwort."""
    body = (await api.get("/__test__/boom")).json()

    serialised = repr(body)
    assert "RuntimeError" not in serialised
    assert "constraint" not in serialised
    assert "row 42" not in serialised


async def test_the_traceback_reaches_the_log_with_the_same_reference(
    api: AsyncClient, captured_logs: list[dict[str, object]]
) -> None:
    """Der Code ist nur etwas wert, wenn er auf beiden Seiten steht."""
    body = (await api.get("/__test__/boom")).json()

    entries = [e for e in captured_logs if e.get("event") == "unhandled_exception"]
    assert entries, "Der unerwartete Fehler muss protokolliert werden, nicht nur beantwortet"
    assert entries[0]["reference"] == body["reference"]


async def test_a_typed_problem_still_wins_over_the_catch_all(api: AsyncClient) -> None:
    """Die Reihenfolge der Handler ist keine Kosmetik: fienge der Auffang-Handler auch
    `ProblemException`, würde jeder Fachfehler zu einer 500."""
    resp = await api.get("/__test__/problem")

    assert resp.status_code == 418
    body = resp.json()
    assert body["type"].endswith("#teapot")
    assert body["detail"] == "kurz und klar"
    assert body["reference"]
