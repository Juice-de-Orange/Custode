"""Keyset (cursor) pagination helpers — opaque cursor over ``(updated_at, id)``.
Never OFFSET (ARCHITECTURE §7)."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - Pydantic generic models use Generic[T]
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(updated_at: datetime, id_: str) -> str:
    raw = json.dumps({"u": updated_at.isoformat(), "id": id_}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[str, str]:
    data: dict[str, Any] = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return str(data["u"]), str(data["id"])
