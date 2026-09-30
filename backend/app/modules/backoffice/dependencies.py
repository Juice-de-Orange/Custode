"""FastAPI dependencies for the Betreiber-Konsole (`/ops`). The ops stack is isolated: it runs on an
``ops_readonly`` DB session (no household context, no fact-table access) and authenticates operators
via an opaque Redis bearer token — never the user cookie/principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.db.engine import get_ops_actions_sessionmaker, get_ops_sessionmaker
from app.kernel.http.problem import ProblemException
from app.modules.backoffice.models import Operator
from app.modules.backoffice.session import load_ops_session


async def get_ops_session() -> AsyncIterator[AsyncSession]:
    """An ``ops_readonly`` session (reads aggregate views + the operators table only)."""
    async with get_ops_sessionmaker()() as session:
        yield session


OpsSession = Annotated[AsyncSession, Depends(get_ops_session)]


async def get_ops_actions_session() -> AsyncIterator[AsyncSession]:
    """An ``ops_actions`` session for audited write actions (banners, audit_log, …). Commits the
    unit of work on success; rolls back on error."""
    async with get_ops_actions_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


OpsActionsSession = Annotated[AsyncSession, Depends(get_ops_actions_session)]


def bearer_token(request: Request) -> str | None:
    """Extract a Bearer token from the Authorization header, or ``None``."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def current_operator(request: Request, session: OpsSession) -> Operator:
    """Resolve the authenticated, still-active operator from the bearer token. 401 otherwise
    (fail-closed)."""
    token = bearer_token(request)
    if token is None:
        raise ProblemException(slug="unauthorized", title="Nicht angemeldet", status=401)
    operator_id = await load_ops_session(token)
    if operator_id is None:
        raise ProblemException(slug="unauthorized", title="Sitzung ungültig", status=401)
    operator = await session.get(Operator, operator_id)
    if operator is None or not operator.is_active:
        raise ProblemException(slug="unauthorized", title="Operator inaktiv", status=401)
    return operator


CurrentOperator = Annotated[Operator, Depends(current_operator)]
