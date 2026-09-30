"""accounts — users, households, memberships, invites + RLS

Revision ID: 0002_accounts
Revises: 0001_baseline
Create Date: 2026-06-15

Identity & tenancy tables (KONZEPT §5.1/§10). `users` is global; the others are
household-scoped. RLS (ARCHITECTURE §9): household-scoped tables filter on
`app.household_id`; `users` is visible to self (`app.user_id`) or co-members of
the active household, and writable only to one's own row.
"""

from __future__ import annotations

from alembic import op

revision = "0002_accounts"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_SCOPED = ("households", "memberships", "invites")
_ALL = ("users", *_SCOPED)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            email varchar(320) UNIQUE,
            password_hash varchar(255),
            display_name varchar(100) NOT NULL,
            locale varchar(10) NOT NULL DEFAULT 'de',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE households (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            name varchar(120) NOT NULL,
            settings_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            tz varchar(40) NOT NULL DEFAULT 'Europe/Vienna',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE memberships (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id),
            role varchar(10) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CONSTRAINT uq_memberships_household_id_user_id UNIQUE (household_id, user_id)
        );
        """
    )
    op.execute("CREATE INDEX ix_memberships_household_id ON memberships (household_id);")
    op.execute("CREATE INDEX ix_memberships_user_id ON memberships (user_id);")
    op.execute(
        """
        CREATE TABLE invites (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            code varchar(48) NOT NULL UNIQUE,
            role varchar(10) NOT NULL DEFAULT 'member',
            expires_at timestamptz NOT NULL,
            max_uses integer NOT NULL DEFAULT 1,
            uses integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_invites_household_id ON invites (household_id);")

    # Shared updated_at/version trigger (function from 0001) + enable/force RLS.
    for table in _ALL:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    op.execute(
        "CREATE POLICY household_isolation ON households "
        "USING (id = current_setting('app.household_id', true)::uuid);"
    )
    for table in ("memberships", "invites"):
        op.execute(
            f"CREATE POLICY household_isolation ON {table} "
            f"USING (household_id = current_setting('app.household_id', true)::uuid);"
        )
    op.execute(
        """
        CREATE POLICY user_visibility ON users
        USING (
            id = current_setting('app.user_id', true)::uuid
            OR EXISTS (
                SELECT 1 FROM memberships m
                WHERE m.user_id = users.id
                  AND m.household_id = current_setting('app.household_id', true)::uuid
            )
        )
        WITH CHECK (id = current_setting('app.user_id', true)::uuid);
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON users, households, memberships, invites TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in reversed(_ALL):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
