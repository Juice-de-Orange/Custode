"""Operator-set global feature-flag overrides (ADR-0015). A kernel concern: the app reads them when
resolving household flags (``accounts.me``); the ops console sets them (audited). Overrides sit on
the **global** layer of ``get_household_flags`` — between env defaults and household settings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class GlobalFlag(Base):
    """One operator-set global flag override (``key`` -> ``enabled``). Absence = no override (the
    env default / household setting applies)."""

    __tablename__ = "global_flags"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def load_global_flags(session: AsyncSession) -> dict[str, bool]:
    """All operator-set global overrides as ``{key: enabled}`` (read on the app session)."""
    rows = await session.execute(select(GlobalFlag.key, GlobalFlag.enabled))
    return {row.key: row.enabled for row in rows}


async def set_global_flag(
    session: AsyncSession, *, key: str, enabled: bool, updated_by: uuid.UUID | None
) -> None:
    """Upsert a global override (write on the ops_actions session). The caller audits the change."""
    await session.execute(
        text(
            "INSERT INTO global_flags (key, enabled, updated_by, updated_at) "
            "VALUES (:key, :enabled, :updated_by, now()) "
            "ON CONFLICT (key) DO UPDATE SET "
            "enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = now()"
        ),
        {"key": key, "enabled": enabled, "updated_by": updated_by},
    )
    await session.flush()
