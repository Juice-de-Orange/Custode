"""recipes — recipes + recipe_ingredients (household-scoped, +RLS) (KONZEPT §5.2)

Revision ID: 0016_recipes
Revises: 0015_users_child_pin
Create Date: 2026-06-19

Erstes Phase-2-Feature-Modul. Zwei household-scoped Fachtabellen mit den Standard-Mixin-Spalten
(``version`` ist der Rezept-ETag für PATCH+If-Match, ADR-0029). RLS ``household_isolation``
(USING+WITH CHECK); gemeinsamer ``set_updated_and_version``-Trigger (aus 0001).
``recipe_ingredients`` behält ``raw_text`` immer; ``ingredient_id`` = kanonischer Link (S4).
"""

from __future__ import annotations

from alembic import op

revision = "0016_recipes"
down_revision = "0015_users_child_pin"
branch_labels = None
depends_on = None

_TABLES = ("recipes", "recipe_ingredients")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE recipes (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            servings integer NOT NULL DEFAULT 1,
            steps_md text NOT NULL DEFAULT '',
            prep_minutes integer,
            cook_minutes integer,
            tags varchar[] NOT NULL DEFAULT '{}',
            source_url text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE recipe_ingredients (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            recipe_id uuid NOT NULL REFERENCES recipes(id),
            raw_text text NOT NULL,
            qty varchar(40),
            unit varchar(40),
            ingredient_id uuid,
            position integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_recipes_household_id ON recipes (household_id);")
    op.execute(
        "CREATE INDEX ix_recipe_ingredients_household_id ON recipe_ingredients (household_id);"
    )
    op.execute("CREATE INDEX ix_recipe_ingredients_recipe_id ON recipe_ingredients (recipe_id);")

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
                GRANT SELECT, INSERT, UPDATE, DELETE ON recipes, recipe_ingredients TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recipe_ingredients CASCADE;")
    op.execute("DROP TABLE IF EXISTS recipes CASCADE;")
