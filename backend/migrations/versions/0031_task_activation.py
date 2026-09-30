"""tasks — activation_json + 'armed' status for action chains (KONZEPT §5.17)

Revision ID: 0031_task_activation
Revises: 0030_captures
Create Date: 2026-06-23

Aktionsketten (P4-S9b): ``task_instances`` bekommt ``activation_json`` (z. B.
``{"on_item_checked": "<item_id>"}``) und den neuen Status ``armed`` — eine vorgemerkte
Folge-Aufgabe, die erst beim passenden ``shopping.item.checked`` (capture-Handler) auf ``open``
scharf geschaltet wird. Additiv: bestehende Instanzen behalten ``activation_json = NULL``; die
Status-CHECK wird um ``armed`` erweitert.
"""

from __future__ import annotations

from alembic import op

revision = "0031_task_activation"
down_revision = "0030_captures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_instances ADD COLUMN activation_json jsonb;")
    op.execute("ALTER TABLE task_instances DROP CONSTRAINT task_instances_status_check;")
    op.execute(
        "ALTER TABLE task_instances ADD CONSTRAINT task_instances_status_check "
        "CHECK (status IN ('open', 'done', 'expired', 'armed'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_instances DROP CONSTRAINT task_instances_status_check;")
    op.execute(
        "ALTER TABLE task_instances ADD CONSTRAINT task_instances_status_check "
        "CHECK (status IN ('open', 'done', 'expired'));"
    )
    op.execute("ALTER TABLE task_instances DROP COLUMN activation_json;")
