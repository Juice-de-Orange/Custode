from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class ObjectLink(HouseholdScoped, Base):
    """A typed link between two arbitrary objects (KONZEPT §5.12 / Phase 7): recipe<->guide,
    task<->guide, note<->guide … Each endpoint is a string discriminator (``*_type``) + a bare
    UUID (``*_id``) — **no cross-module FK**. Endpoints are stored in a canonical order (the
    smaller ``(type, id)`` first) so a link is direction-independent and a symmetric duplicate
    cannot be created. RLS: household_id."""

    __tablename__ = "object_links"

    src_type: Mapped[str] = mapped_column(String(40))
    src_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    dst_type: Mapped[str] = mapped_column(String(40))
    dst_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    relation: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
