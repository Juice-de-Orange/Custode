"""retention maint — cross-household hard-delete access for custode_maint

Revision ID: 0053_retention_maint
Revises: 0052_guide_attachments
Create Date: 2026-06-29

Der Retention-Reaper läuft als ``custode_maint`` und löscht getombstonete Zeilen (``deleted_at``
älter als das Fenster) über ALLE Haushalte (ARCH §9 — "Hard-Delete nur via Retention-Job"). Wie
beim Sync-Ops-Reaper (0021) braucht ``custode_maint`` je Tabelle eine permissive Policy
``maint_all`` (additiv zu ``household_isolation``; ``custode_app`` bleibt haushaltsbeschränkt) plus
``SELECT, DELETE``. Kind-Zeilen (z. B. ``note_versions``) hängen per FK ``ON DELETE CASCADE`` und
werden vom FK-Mechanismus entfernt — unabhängig von RLS/Grants.

``notes`` ist die erste Tabelle (echtes Soft-Delete). Die Liste spiegelt ``_RETENTION_TABLES`` in
``app/worker.py``; weitere kommen hinzu, sobald sie Soft-Delete + Papierkorb haben.
"""

from __future__ import annotations

from alembic import op

revision = "0053_retention_maint"
down_revision = "0052_guide_attachments"
branch_labels = None
depends_on = None

_TABLES = ("notes",)


def _grant_maint(table: str) -> str:
    # ``table`` comes from the code-defined ``_TABLES`` literal, never user input.
    return (
        f"DO $$ BEGIN "  # noqa: S608
        f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN "
        f"EXECUTE 'CREATE POLICY maint_all ON {table} TO custode_maint "
        f"USING (true) WITH CHECK (true)'; "
        f"GRANT SELECT, DELETE ON {table} TO custode_maint; "
        f"END IF; END $$;"
    )


def upgrade() -> None:
    for table in _TABLES:
        op.execute(_grant_maint(table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS maint_all ON {table};")
