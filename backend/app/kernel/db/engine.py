"""Lazy async engine + session factory. Nothing connects at import time, so the
app boots and exports OpenAPI without a database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


_maint_engine: AsyncEngine | None = None
_maint_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_maint_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory for the cross-household maintenance role (outbox dispatcher,
    retention jobs). Falls back to the app URL if no dedicated maint URL is set."""
    global _maint_engine, _maint_sessionmaker
    if _maint_sessionmaker is None:
        settings = get_settings()
        url = settings.database_url_maint or settings.database_url
        _maint_engine = create_async_engine(url, pool_pre_ping=True)
        _maint_sessionmaker = async_sessionmaker(_maint_engine, expire_on_commit=False)
    return _maint_sessionmaker


_ops_engine: AsyncEngine | None = None
_ops_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_ops_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory for the Betreiber-Konsole role ``ops_readonly`` (ADR-0015/0071): reads the
    aggregate views + the ``operators`` auth table, never a fact table (no fact-table grant). Falls
    back to the app URL only in dev if no dedicated ops URL is set."""
    global _ops_engine, _ops_sessionmaker
    if _ops_sessionmaker is None:
        settings = get_settings()
        url = settings.database_url_ops or settings.database_url
        _ops_engine = create_async_engine(url, pool_pre_ping=True)
        _ops_sessionmaker = async_sessionmaker(_ops_engine, expire_on_commit=False)
    return _ops_sessionmaker


_ops_actions_engine: AsyncEngine | None = None
_ops_actions_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_ops_actions_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory for the ``ops_actions`` role (ADR-0015): writes the append-only ``audit_log``
    and ops-owned tables, runs defined action procedures. Falls back to the app URL only in dev."""
    global _ops_actions_engine, _ops_actions_sessionmaker
    if _ops_actions_sessionmaker is None:
        settings = get_settings()
        url = settings.database_url_ops_actions or settings.database_url
        _ops_actions_engine = create_async_engine(url, pool_pre_ping=True)
        _ops_actions_sessionmaker = async_sessionmaker(_ops_actions_engine, expire_on_commit=False)
    return _ops_actions_sessionmaker
