"""recipes.photo_key — optionales Rezept-Foto (Filesystem-Blob-Storage)

Revision ID: 0022_recipe_photo
Revises: 0021_sync_ops_maint
Create Date: 2026-06-21

Additive expand-Migration: nullable ``photo_key`` (Storage-Key des JPEG). Keine RLS-Änderung
(``recipes`` ist bereits household-scoped). Foto-Bytes liegen im Blob-Storage, nicht in der DB.
"""

from __future__ import annotations

from alembic import op

revision = "0022_recipe_photo"
down_revision = "0021_sync_ops_maint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recipes ADD COLUMN photo_key varchar(80);")


def downgrade() -> None:
    op.execute("ALTER TABLE recipes DROP COLUMN IF EXISTS photo_key;")
