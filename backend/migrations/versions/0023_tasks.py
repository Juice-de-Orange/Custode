"""tasks — task_templates + task_instances (household-scoped, +RLS) (KONZEPT §5.9)

Revision ID: 0023_tasks
Revises: 0022_recipe_photo
Create Date: 2026-06-23

Erstes Phase-4-Feature-Modul. Zwei household-scoped Fachtabellen mit den Standard-Mixin-Spalten
(``version`` ist der ETag für PATCH+If-Match, ADR-0034). RLS ``household_isolation`` (USING+WITH
CHECK); gemeinsamer ``set_updated_and_version``-Trigger (aus 0001). ``points`` ist eine inerte
Spalte (``CHECK >= 0``) — keine Ledger-Buchung in S1. ``task_instances`` ist eine Status-Maschine
(``open|done|expired``), nie hard-deleted; ``done_by``/``done_at`` werden serverseitig gestempelt.
Verschoben (additiv in Folge-Slices): ``rrule``, ``pool``, ``room_id``, Rotation-Durchsetzung.
"""

from __future__ import annotations

from alembic import op

revision = "0023_tasks"
down_revision = "0022_recipe_photo"
branch_labels = None
depends_on = None

_TABLES = ("task_templates", "task_instances")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE task_templates (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            description text,
            points integer NOT NULL DEFAULT 0 CHECK (points >= 0),
            duration_est_minutes integer,
            outdoor boolean NOT NULL DEFAULT false,
            rotation varchar(10) NOT NULL DEFAULT 'open'
                CHECK (rotation IN ('fair', 'fixed', 'open')),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE task_instances (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            template_id uuid REFERENCES task_templates(id),
            title varchar(200) NOT NULL,
            points integer NOT NULL DEFAULT 0 CHECK (points >= 0),
            assigned_to uuid,
            due_at timestamptz,
            status varchar(8) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'done', 'expired')),
            done_at timestamptz,
            done_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_task_templates_household_id ON task_templates (household_id);")
    op.execute("CREATE INDEX ix_task_instances_household_id ON task_instances (household_id);")
    op.execute("CREATE INDEX ix_task_instances_template_id ON task_instances (template_id);")
    op.execute("CREATE INDEX ix_task_instances_status ON task_instances (status);")

    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY household_isolation ON {table} "
            f"USING (household_id = current_setting('app.household_id', true)::uuid) "
            f"WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
        )

    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON task_templates, task_instances TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS task_instances CASCADE;")
    op.execute("DROP TABLE IF EXISTS task_templates CASCADE;")
