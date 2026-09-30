"""accounts child accounts — users.username + users.pin_hash (PIN login) (KONZEPT §5.1/§8)

Revision ID: 0015_users_child_pin
Revises: 0014_users_settings_json
Create Date: 2026-06-19

Adds ``username`` + ``pin_hash`` to ``users`` for child accounts (S12): a child has no e-mail/
password but a household-unique username and an Argon2id-hashed PIN. Both NULL for adult accounts.
Additive/expand-only; username uniqueness is enforced per household at the application layer (a
global UNIQUE would wrongly forbid the same child name across households). RLS/grants unchanged —
the admin creates the child self-scoped to the new id; child login reads it as ``custode_maint``.
"""

from __future__ import annotations

from alembic import op

revision = "0015_users_child_pin"
down_revision = "0014_users_settings_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN username varchar(50);")
    op.execute("ALTER TABLE users ADD COLUMN pin_hash varchar(255);")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS pin_hash;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username;")
