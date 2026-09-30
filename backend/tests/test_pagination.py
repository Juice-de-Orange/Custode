from __future__ import annotations

from datetime import UTC, datetime

from app.kernel.http.pagination import decode_cursor, encode_cursor


def test_cursor_roundtrip() -> None:
    dt = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    cursor = encode_cursor(dt, "abc-123")
    updated_at, id_ = decode_cursor(cursor)
    assert id_ == "abc-123"
    assert updated_at.startswith("2026-06-14T12:00")
