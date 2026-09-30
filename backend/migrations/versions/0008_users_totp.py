"""accounts totp — users.totp_secret + totp_enabled (TOTP-2FA, KONZEPT §8/§10)

Revision ID: 0008_users_totp
Revises: 0007_accounts_maint_reads
Create Date: 2026-06-17

Adds the optional TOTP secret (base32) + an enabled flag to ``users`` (KONZEPT §10 lists
``totp?``). Additive/expand-only; RLS and grants are unchanged — the user updates their own
row via the ``users`` self-policy, and login reads it as ``custode_maint`` (which already
has SELECT on users from 0006). Encryption-at-rest + recovery codes are later increments.
"""

from __future__ import annotations

from alembic import op

revision = "0008_users_totp"
down_revision = "0007_accounts_maint_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN totp_secret varchar(64);")
    op.execute("ALTER TABLE users ADD COLUMN totp_enabled boolean NOT NULL DEFAULT false;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_enabled;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_secret;")
