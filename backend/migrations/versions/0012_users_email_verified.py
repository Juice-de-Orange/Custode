"""accounts email verification — users.email_verified_at (KONZEPT §5.1/§9)

Revision ID: 0012_users_email_verified
Revises: 0011_login_events
Create Date: 2026-06-19

Adds an optional ``email_verified_at`` timestamp to ``users`` (NULL = unverified). Additive/
expand-only; RLS and grants are unchanged — the user confirms their own row via the ``users``
self-policy (``id = app.user_id``), and the existing ``custode_maint`` SELECT (0006) covers any
read. The confirm flow sets the timestamp; a verification e-mail is sent at registration (S9b).
"""

from __future__ import annotations

from alembic import op

revision = "0012_users_email_verified"
down_revision = "0011_login_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN email_verified_at timestamptz;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at;")
