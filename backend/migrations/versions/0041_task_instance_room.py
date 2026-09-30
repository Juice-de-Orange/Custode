"""tasks — task_instances.room_id (Heatmap als Aktionsfläche) (KONZEPT §5.9, S-13)

Revision ID: 0041_task_instance_room
Revises: 0040_calendar_event_overrides
Create Date: 2026-06-24

Phase 5, P5-S11 (Synergie S-13): ``task_instances`` bekommt ein optionales ``room_id``. So kann eine
**ad-hoc** Aufgabe (ohne Template) direkt einem Raum zugeordnet werden — aus der Heatmap heraus
(„Raum rot → Aufgabe anlegen"). Der effektive Raum einer Instanz ist
``COALESCE(instance.room_id, template.room_id)``; die Heatmap zählt beide. Additiv, nullable.
"""

from __future__ import annotations

from alembic import op

revision = "0041_task_instance_room"
down_revision = "0040_calendar_event_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_instances ADD COLUMN room_id uuid;")
    op.execute("CREATE INDEX ix_task_instances_room_id ON task_instances (room_id);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_task_instances_room_id;")
    op.execute("ALTER TABLE task_instances DROP COLUMN room_id;")
