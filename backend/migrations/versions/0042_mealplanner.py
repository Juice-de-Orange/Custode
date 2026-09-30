"""mealplanner — meal_plans + meal_slots (household-scoped, +RLS) (KONZEPT §5.4)

Revision ID: 0042_mealplanner
Revises: 0041_task_instance_room
Create Date: 2026-06-24

Phase 6, P6-S1: der manuelle Wochenplan. ``meal_plans`` = eine Woche je Haushalt (Montag als
``week_start``); ``meal_slots`` = ein Eintrag pro Tag/Mahlzeit, entweder ein Rezept (``recipe_id``,
ohne DB-FK — Auflösung über recipes.api, Modulgrenze) oder ein Freitext, plus „wer kocht"
(``cook_id``). Beide household-scoped, RLS ``household_isolation``, gemeinsamer Versions-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0042_mealplanner"
down_revision = "0041_task_instance_room"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY household_isolation ON {table} "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO custode_app;
            END IF;
        END $$;
        """  # noqa: S608 — ``table`` is a hardcoded literal, not user input
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE meal_plans (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            week_start date NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_meal_plans_household_id ON meal_plans (household_id);")
    op.execute(
        "CREATE UNIQUE INDEX uq_meal_plans_household_week ON meal_plans (household_id, week_start) "
        "WHERE deleted_at IS NULL;"
    )
    _rls("meal_plans")

    op.execute(
        """
        CREATE TABLE meal_slots (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            plan_id uuid NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
            day_of_week smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
            slot varchar(12) NOT NULL CHECK (slot IN ('breakfast','lunch','dinner','snack')),
            recipe_id uuid,
            free_text varchar(200),
            cook_id uuid,
            note varchar(200),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_meal_slots_household_id ON meal_slots (household_id);")
    op.execute("CREATE INDEX ix_meal_slots_plan_id ON meal_slots (plan_id);")
    op.execute(
        "CREATE UNIQUE INDEX uq_meal_slots_plan_day_slot "
        "ON meal_slots (plan_id, day_of_week, slot) WHERE deleted_at IS NULL;"
    )
    _rls("meal_slots")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meal_slots CASCADE;")
    op.execute("DROP TABLE IF EXISTS meal_plans CASCADE;")
