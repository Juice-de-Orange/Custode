from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Guide(HouseholdScoped, Base):
    """A household guide / „Anleitung" (KONZEPT §5, Phase 7): markdown body with a category + tags.
    RLS: household_id. ``version`` (mixin/trigger) is the ETag for PATCH + If-Match. A generated
    ``search_tsv`` (German FTS) backs ``GET ?q=`` — read-only, not mapped here. ACL and attachments
    are later slices. ``contact_id`` (optional) names a household member as the go-to person — a
    bare member UUID, **no FK** to accounts (module boundary); the name is resolved client-side."""

    __tablename__ = "guides"

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text, server_default=text("''"))
    category: Mapped[str] = mapped_column(String(80), server_default=text("''"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class GuideAttachment(HouseholdScoped, Base):
    """A file attached to a guide (KONZEPT §5, Phase 7). Like recipe photos (ADR-0033) the **bytes
    live in blob storage**; the DB keeps only metadata + a server-generated ``storage_key`` (never
    user input). ``guide_id`` is a bare module-internal UUID; deleting a guide cascades to its
    attachments in the service (soft-delete + blob removal), so there is no DB-level FK cascade."""

    __tablename__ = "guide_attachments"

    guide_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
