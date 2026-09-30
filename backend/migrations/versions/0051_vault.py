"""vault — clientseitig verschlüsselte Geheimnisse, Server nur Ciphertext (+RLS) §5

Revision ID: 0051_vault
Revises: 0050_guide_contact
Create Date: 2026-06-24

Phase 7, P7-S13 (ADR-0067): Backend-Fundament des Vaults. Zwei household-scoped Tabellen, beide mit
RLS ``household_isolation`` (USING + WITH CHECK) + FORCE + Versions-Trigger:

- ``vault_key_envelopes``: pro Mitglied (bzw. haushaltsweit für Recovery) umschlossene Kopien des
  Haushalts-Vault-Schlüssels. ``wrapped_key`` (Base64-Text) + ``wrap_meta`` (JSONB, opak: KDF-Algo/
  -Parameter, Salt, Nonce — client-definiert). ``kind`` in (passphrase|recovery); Recovery hat
  ``member_id IS NULL``.
- ``vault_items``: die Geheimnisse als ``ciphertext`` (Base64-Text) + ``item_meta`` (JSONB, opak:
  Nonce, verschlüsselter Name/Typ — **kein** Klartext-Label). ``key_version`` referenziert den
  Schlüssel, mit dem verschlüsselt wurde.

Der Server interpretiert **keine** dieser Bytes; er sieht nur Ciphertext (kein Klartext, keine PII).
"""

from __future__ import annotations

from alembic import op

revision = "0051_vault"
down_revision = "0050_guide_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE vault_key_envelopes (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid,
            kind varchar(20) NOT NULL CHECK (kind IN ('passphrase', 'recovery')),
            key_version integer NOT NULL DEFAULT 1,
            wrapped_key text NOT NULL,
            wrap_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CHECK ((kind = 'recovery') = (member_id IS NULL))
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_vault_key_envelopes_household_id ON vault_key_envelopes (household_id);"
    )
    # One passphrase envelope per (member, version); one recovery envelope per (household, version).
    op.execute(
        "CREATE UNIQUE INDEX ux_vault_envelope_passphrase ON vault_key_envelopes "
        "(household_id, member_id, key_version) WHERE kind = 'passphrase' AND deleted_at IS NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_vault_envelope_recovery ON vault_key_envelopes "
        "(household_id, key_version) WHERE kind = 'recovery' AND deleted_at IS NULL;"
    )
    op.execute("ALTER TABLE vault_key_envelopes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE vault_key_envelopes FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON vault_key_envelopes "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON vault_key_envelopes TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_vault_key_envelopes_updated BEFORE UPDATE ON vault_key_envelopes "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )

    op.execute(
        """
        CREATE TABLE vault_items (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            author_id uuid NOT NULL,
            key_version integer NOT NULL DEFAULT 1,
            ciphertext text NOT NULL,
            item_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_vault_items_household_id ON vault_items (household_id);")
    op.execute("ALTER TABLE vault_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE vault_items FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON vault_items "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON vault_items TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_vault_items_updated BEFORE UPDATE ON vault_items "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vault_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS vault_key_envelopes CASCADE;")
