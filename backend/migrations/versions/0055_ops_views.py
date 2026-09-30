"""ops aggregate views — Betreiber-Konsole liest nur Aggregate, nie Fachtabellen (ADR-0015/0071)

Revision ID: 0055_ops_views
Revises: 0054_feedback
Create Date: 2026-06-29

Phase 8, P8-S7a (Ops-Console-Fundament): zwei **Aggregat-Views** für die Betreiber-Konsole und die
DB-Rollen-Trennung. Die Views gehören ``custode_maint`` und sind **security definer**
(``security_invoker`` bleibt aus): Beim Abfragen laufen die Tabellenzugriffe mit den Rechten +
RLS-Policies des **Owners** ``custode_maint``, dessen ``maint_all``-Policies (Migrationen 0006/0007)
alle Haushalte sichtbar machen. ``ops_readonly`` erhält **SELECT nur auf die Views** — **kein**
Fachtabellen-Recht. So sieht die Konsole Kennzahlen, nie einzelne Fachzeilen (ADR-0015).

Rollen (``ops_readonly``/``ops_actions``) werden in ``infra/postgres/init.sql`` provisioniert; die
Grants hier sind per ``pg_roles``-Guard gegen fehlende Rollen abgesichert (wie der maint-Pfad).
"""

from __future__ import annotations

from alembic import op

revision = "0055_ops_views"
down_revision = "0054_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Single-row global counters. Soft-deleted rows excluded; adult vs. child split.
    op.execute(
        """
        CREATE VIEW usage_counters AS
        SELECT
            (SELECT count(*) FROM households WHERE deleted_at IS NULL) AS households,
            (SELECT count(*) FROM users WHERE deleted_at IS NULL) AS users,
            (SELECT count(*) FROM memberships
                 WHERE deleted_at IS NULL AND role IN ('admin', 'member')) AS adult_members,
            (SELECT count(*) FROM memberships
                 WHERE deleted_at IS NULL AND role = 'child') AS children;
        """
    )
    # New households + new users per calendar day (signup curve), no PII.
    op.execute(
        """
        CREATE VIEW daily_metrics AS
        SELECT
            day,
            count(*) FILTER (WHERE kind = 'household') AS new_households,
            count(*) FILTER (WHERE kind = 'user') AS new_users
        FROM (
            SELECT created_at::date AS day, 'household' AS kind FROM households
            UNION ALL
            SELECT created_at::date AS day, 'user' AS kind FROM users
        ) AS s
        GROUP BY day;
        """
    )
    # Owner = custode_maint so the (security-definer) views aggregate across all households via its
    # maint_all policies, while ops_readonly needs no fact-table grant. Granting SELECT on the views
    # only is the whole point (ADR-0015). All guarded against missing roles (CI/test provisioning).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                -- ALTER … OWNER TO requires the recipient to hold CREATE on the schema; grant it
                -- just for the ownership transfer, then revoke (ownership persists without it).
                GRANT CREATE ON SCHEMA public TO custode_maint;
                ALTER VIEW usage_counters OWNER TO custode_maint;
                ALTER VIEW daily_metrics OWNER TO custode_maint;
                REVOKE CREATE ON SCHEMA public FROM custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON usage_counters, daily_metrics TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS daily_metrics;")
    op.execute("DROP VIEW IF EXISTS usage_counters;")
