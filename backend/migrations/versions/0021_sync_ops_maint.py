"""sync_client_ops maint — cross-household reaper access for custode_maint

Revision ID: 0021_sync_ops_maint
Revises: 0020_shopping_basics
Create Date: 2026-06-20

Der Sync-Idempotenz-Reaper läuft als ``custode_maint`` und löscht ``sync_client_ops``-Marker
über ALLE Haushalte (Hygiene; ARCH §8.4/§10). Permissive Policy ``TO custode_maint``, additiv
zu ``household_isolation`` (``custode_app`` bleibt haushaltsbeschränkt). Re-Apply eines Ops nach dem
Reap ist unter LWW unkritisch (Feld-Merge-Upsert ist meist ein No-Op).
"""

from __future__ import annotations

from alembic import op

revision = "0021_sync_ops_maint"
down_revision = "0020_shopping_basics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON sync_client_ops TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, DELETE ON sync_client_ops TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS maint_all ON sync_client_ops;")
