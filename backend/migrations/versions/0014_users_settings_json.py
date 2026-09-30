"""accounts profile — users.settings_json (self-service profile blob) (KONZEPT §5.1)

Revision ID: 0014_users_settings_json
Revises: 0013_consents
Create Date: 2026-06-19

Adds ``users.settings_json`` (jsonb, default ``{}``) for self-service profile data: work hours,
dietary preferences/allergies, per-channel notification settings. Additive/expand-only; the
existing ``users`` self-policy (0002) governs the update and the shared ``set_updated_and_version``
trigger bumps ``version`` (the profile ETag for If-Match optimistic concurrency).
"""

from __future__ import annotations

from alembic import op

revision = "0014_users_settings_json"
down_revision = "0013_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN settings_json jsonb NOT NULL DEFAULT '{}'::jsonb;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS settings_json;")
