"""tasks — rooms + task_templates.room_id (household-scoped, +RLS) (KONZEPT §5.9/§5.8)

Revision ID: 0027_rooms
Revises: 0026_task_awarded_points
Create Date: 2026-06-23

Räume (P4-S6): ``rooms`` (household-scoped, +RLS) mit ``decay_days`` (Verfall-Fenster);
Task-Templates erhalten ein optionales ``room_id``. Die Raum-Heatmap ist **berechnet** (f(letzte
Erledigung der Tasks des Raums, decay_days)) und wird NICHT gespeichert. Gemeinsamer
``set_updated_and_version``-Trigger; ``room_id`` additiv-nullable.
"""

from __future__ import annotations

from alembic import op

revision = "0027_rooms"
down_revision = "0026_task_awarded_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rooms (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            name varchar(100) NOT NULL,
            icon varchar(40),
            decay_days integer NOT NULL CHECK (decay_days > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_rooms_household_id ON rooms (household_id);")
    op.execute("ALTER TABLE task_templates ADD COLUMN room_id uuid REFERENCES rooms(id);")
    op.execute("CREATE INDEX ix_task_templates_room_id ON task_templates (room_id);")

    op.execute(
        "CREATE TRIGGER trg_rooms_updated BEFORE UPDATE ON rooms "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE rooms ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE rooms FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON rooms "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )

    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON rooms TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_templates DROP COLUMN IF EXISTS room_id;")
    op.execute("DROP TABLE IF EXISTS rooms CASCADE;")
