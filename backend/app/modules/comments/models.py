from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Comment(HouseholdScoped, Base):
    """A comment/thread entry on an arbitrary object (KONZEPT §5.12). ``object_type`` is a string
    discriminator (``"guide"``/``"recipe"``/``"task"``…) and ``object_id`` a bare UUID — **no
    cross-module FK** (the commented module need not know about comments). RLS: household_id."""

    __tablename__ = "comments"

    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    body_md: Mapped[str] = mapped_column(Text)
