"""wearables wire shapes (P9-S5). Tokens are write-only: nothing here ever carries a token,
a refresh token, or the ciphertext."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.wearables.types import ALL_CONSENT_TYPES


def _validate_consent_types(value: list[str]) -> list[str]:
    """Reject unknown types loudly instead of silently ignoring them — a typo must not look like
    a successful consent. Deduplicated and returned in the canonical order so the resulting
    scope set and the ledger rows are stable."""
    unknown = sorted(set(value) - set(ALL_CONSENT_TYPES))
    if unknown:
        raise ValueError(f"unknown consent types: {', '.join(unknown)}")
    return [t for t in ALL_CONSENT_TYPES if t in set(value)]


class AuthorizeRequest(BaseModel):
    """Start the OAuth flow for the chosen data types (Art. 9: consent per type, KONZEPT §5.15).

    At least one type is required: a connection without any consented type would collect nothing
    and have no legal basis to exist."""

    consent_types: list[str] = Field(min_length=1)

    @field_validator("consent_types")
    @classmethod
    def _known_types(cls, value: list[str]) -> list[str]:
        return _validate_consent_types(value)


class AuthorizeResponse(BaseModel):
    """Where to send the browser. The state token is embedded in the URL and deliberately not
    exposed as a separate field — nothing client-side needs it."""

    authorize_url: str


class ConsentUpdate(BaseModel):
    """Replace the consented types of an existing connection.

    Empty list is allowed and meaningful: it withdraws everything, which disconnects (a
    connection without consent must not survive). Types dropped here have their stored values
    erased immediately."""

    consent_types: list[str]

    @field_validator("consent_types")
    @classmethod
    def _known_types(cls, value: list[str]) -> list[str]:
        return _validate_consent_types(value)


class ConnectionResponse(BaseModel):
    """One wearable connection. ``has_tokens`` stands in for the credentials; the tokens
    themselves never leave the server."""

    id: uuid.UUID
    member_id: uuid.UUID
    provider: str
    status: str
    has_tokens: bool
    #: Currently consented data types, folded from the append-only ledger.
    consent_types: list[str]
    scopes: list[str]
    last_sync_at: datetime | None = None
    #: Failure category slug of the last run; null = fine.
    last_error: str | None = None
