"""tasks — task_instances.awarded_points (verfallener Gutschrift-Betrag) (KONZEPT §5.9)

Revision ID: 0026_task_awarded_points
Revises: 0025_rewards
Create Date: 2026-06-23

Wert-Verfall (P4-S4): Beim Erledigen wird der **effektive** (ggf. verfallene) Punktwert ins Ledger
gebucht. ``awarded_points`` hält genau diesen Betrag je Instanz fest — für Anzeige („du hast X
verdient") und Audit gegen das Ledger. Additive, nullable Spalte (NULL = noch nicht erledigt / vor
diesem Slice erledigt). Kein RLS-/Policy-Sonderfall (bestehende Tabelle).
"""

from __future__ import annotations

from alembic import op

revision = "0026_task_awarded_points"
down_revision = "0025_rewards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_instances ADD COLUMN awarded_points integer;")


def downgrade() -> None:
    op.execute("ALTER TABLE task_instances DROP COLUMN IF EXISTS awarded_points;")
