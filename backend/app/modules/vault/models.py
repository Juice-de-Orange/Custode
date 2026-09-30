from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class VaultKeyEnvelope(HouseholdScoped, Base):
    """A wrapped copy of the household vault key (KONZEPT §5, ADR-0067). The key is encrypted
    client-side under a member's passphrase-derived key (``kind='passphrase'``, ``member_id`` set)
    or under a household recovery code (``kind='recovery'``, ``member_id`` NULL). The server stores
    only the opaque ``wrapped_key`` (base64) + ``wrap_meta`` (client-defined KDF params/salt/nonce)
    and never decrypts anything. RLS: household_id."""

    __tablename__ = "vault_key_envelopes"

    member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    key_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    wrapped_key: Mapped[str] = mapped_column(Text)
    wrap_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class VaultItem(HouseholdScoped, Base):
    """A secret stored in the household vault (KONZEPT §5, ADR-0067). Encrypted client-side under
    the household vault key; the server holds only the opaque ``ciphertext`` (base64) +
    ``item_meta`` (client-defined: nonce, encrypted name/type — **no plaintext label**, no PII).
    ``key_version``
    names the key version it was encrypted under. ``version`` (mixin/trigger) is the ETag. RLS:
    household_id."""

    __tablename__ = "vault_items"

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    ciphertext: Mapped[str] = mapped_column(Text)
    item_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
