"""Pure-logic unit tests for the admin-continuity invariant (no DB; run locally)."""

from __future__ import annotations

import uuid

from app.modules.accounts.service import would_leave_no_admin


def test_last_admin_is_protected() -> None:
    a = uuid.uuid4()
    assert would_leave_no_admin({a: "admin"}, membership_id=a, new_role="member") is True


def test_another_admin_exists() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    roles = {a: "admin", b: "admin"}
    assert would_leave_no_admin(roles, membership_id=a, new_role="member") is False


def test_demoting_a_non_admin_is_fine() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    roles = {a: "admin", b: "member"}
    assert would_leave_no_admin(roles, membership_id=b, new_role="child") is False


def test_admin_staying_admin_is_fine() -> None:
    a = uuid.uuid4()
    assert would_leave_no_admin({a: "admin"}, membership_id=a, new_role="admin") is False
