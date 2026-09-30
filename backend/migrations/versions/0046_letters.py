"""messaging — letters + letter_reads (household-scoped, +RLS) (KONZEPT §5.12)

Revision ID: 0046_letters
Revises: 0045_note_versions
Create Date: 2026-06-24

Phase 7, P7-S4: „Briefe" — kleine asynchrone Nachrichten an den Haushalt, mit **Gelesen-Status**.
``letters`` (Betreff + Markdown-Body + Absender; ``to_ids`` leer = Rundbrief an alle, sonst die
adressierten Mitglieder). Gelesen-Status als **eigene Tabelle** ``letter_reads`` (eine Zeile je
gelesenem Brief+Nutzer — concurrency-sicher statt JSONB-Read-Modify-Write, ADR-0062). Beide
household-scoped, RLS ``household_isolation`` (USING + WITH CHECK) + FORCE; ``letters`` mit
gemeinsamem Versions-Trigger, ``letter_reads`` append-only (kein Mixin).
"""

from __future__ import annotations

from alembic import op

revision = "0046_letters"
down_revision = "0045_note_versions"
branch_labels = None
depends_on = None


def _isolate(table: str) -> None:
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


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE letters (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            from_id uuid NOT NULL,
            to_ids uuid[] NOT NULL DEFAULT '{}',
            subject varchar(200) NOT NULL,
            body_md text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_letters_household_id ON letters (household_id);")
    _isolate("letters")
    op.execute(
        "CREATE TRIGGER trg_letters_updated BEFORE UPDATE ON letters "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )

    op.execute(
        """
        CREATE TABLE letter_reads (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            letter_id uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            read_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_letter_reads_household_id ON letter_reads (household_id);")
    op.execute(
        "CREATE UNIQUE INDEX uq_letter_reads_letter_user ON letter_reads (letter_id, user_id);"
    )
    _isolate("letter_reads")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS letter_reads CASCADE;")
    op.execute("DROP TABLE IF EXISTS letters CASCADE;")
