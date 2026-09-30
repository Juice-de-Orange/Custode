"""HTTP contracts for ``vault`` (single source for the OpenAPI schema -> web zod client). Every
``*_key``/``ciphertext`` field is opaque base64 the server never decrypts; every ``*_meta`` is a
client-defined JSON blob (KDF params, nonce, encrypted name) — no plaintext, no PII (ADR-0067)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EnvelopeUpsert(BaseModel):
    """Store/replace a wrapped household-key envelope. ``passphrase`` binds to the current member;
    ``recovery`` is household-wide (member_id NULL). The server sets ``member_id`` itself."""

    kind: Literal["passphrase", "recovery"]
    key_version: int = Field(default=1, ge=1)
    wrapped_key: str = Field(min_length=1, max_length=8000)
    wrap_meta: dict[str, Any] = Field(default_factory=dict)


class EnvelopeResponse(BaseModel):
    """A wrapped household-key envelope (opaque to the server)."""

    id: uuid.UUID
    member_id: uuid.UUID | None
    kind: str
    key_version: int
    wrapped_key: str
    wrap_meta: dict[str, Any]
    created_at: datetime


class VaultItemCreate(BaseModel):
    """Store an encrypted secret. ``ciphertext`` + ``item_meta`` are produced client-side."""

    key_version: int = Field(default=1, ge=1)
    ciphertext: str = Field(min_length=1, max_length=500000)
    item_meta: dict[str, Any] = Field(default_factory=dict)


class VaultItemUpdate(BaseModel):
    """Patch an encrypted secret (PATCH + If-Match). Only present fields change."""

    key_version: int | None = Field(default=None, ge=1)
    ciphertext: str | None = Field(default=None, min_length=1, max_length=500000)
    item_meta: dict[str, Any] | None = None


class VaultItemSummary(BaseModel):
    """List item: the encrypted name lives in ``item_meta`` — the secret ``ciphertext`` is **not**
    shipped on list load (fetch the full item to decrypt its body)."""

    id: uuid.UUID
    key_version: int
    item_meta: dict[str, Any]
    updated_at: datetime


class VaultItemResponse(BaseModel):
    """A full encrypted secret incl. its ``ciphertext``."""

    id: uuid.UUID
    author_id: uuid.UUID
    key_version: int
    ciphertext: str
    item_meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
