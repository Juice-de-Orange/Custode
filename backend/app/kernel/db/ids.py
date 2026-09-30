"""UUIDv7 generation (ADR-004). Server-side, Postgres 18 generates ids via the
native ``uuidv7()`` default; this helper is for app-side needs (events, offline,
tests). RFC 9562-conform."""

from __future__ import annotations

import uuid

import uuid_utils


def new_uuid7() -> uuid.UUID:
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)
