"""digest task reads — cross-household SELECT on task_instances for custode_maint

Revision ID: 0063_digest_task_reads
Revises: 0062_feedback_diagnostics
Create Date: 2026-06-30

The weekly digest (P8-S6/S7) counts a household's open/overdue tasks under the **maint role**
(it spans households, ARCHITECTURE §9) via ``tasks.api.count_open_tasks``. ``task_instances`` is a
fact table with ``FORCE ROW LEVEL SECURITY`` whose ``household_isolation`` policy keys off
``app.household_id`` — which the maint path does not set. Mirror 0006/0007: give ``custode_maint`` a
permissive ``maint_all`` read policy (it OR-combines with ``household_isolation``, so it sees all
rows) plus the missing ``SELECT`` grant. Read-only: the digest never writes, so no INSERT/UPDATE/
DELETE grant. Role-guarded so test DBs without ``custode_maint`` still migrate cleanly.
"""

from __future__ import annotations

from alembic import op

revision = "0063_digest_task_reads"
down_revision = "0062_feedback_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON task_instances TO custode_maint USING (true)';
                GRANT SELECT ON task_instances TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS maint_all ON task_instances;")
