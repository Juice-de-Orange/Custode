"""guides.contact_id — Ansprechpartner je Anleitung (additiv, nullable) (KONZEPT §5)

Revision ID: 0050_guide_contact
Revises: 0049_object_links
Create Date: 2026-06-24

Phase 7, P7-S11: eine Anleitung kann eine Ansprechperson („wer kennt sich aus?") benennen.
``contact_id`` ist ein **nacktes Mitglieds-UUID, kein FK** auf accounts (Modulgrenze) — der Name
wird clientseitig aufgelöst. Additive, nullable Spalte (expand/contract: nur expand, kein Backfill).
RLS/Trigger der Tabelle gelten unverändert weiter.
"""

from __future__ import annotations

from alembic import op

revision = "0050_guide_contact"
down_revision = "0049_object_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE guides ADD COLUMN contact_id uuid;")


def downgrade() -> None:
    op.execute("ALTER TABLE guides DROP COLUMN IF EXISTS contact_id;")
