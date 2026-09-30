-- Custode Postgres dev bootstrap. Runs once on first container init, as the
-- superuser (POSTGRES_USER). The application connects as custode_app:
-- LOGIN, NOSUPERUSER, NOBYPASSRLS, and never owns tables — so a forgotten WHERE
-- cannot leak across households (RLS is the second line of defence, ARCHITECTURE §9).
-- Migrations run as the superuser/owner (database_url_admin).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
        CREATE ROLE custode_app LOGIN PASSWORD 'custode'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    -- Maintenance role for cross-household jobs (retention, digests) — narrow policies.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
        CREATE ROLE custode_maint LOGIN PASSWORD 'custode_maint'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    -- Betreiber-Konsole (ADR-0015/ADR-0071): liest NUR Aggregat-Views, nie Fachtabellen.
    -- ops_readonly = KPIs/Health; ops_actions = auditierte Aktions-Prozeduren (S8). Beide ohne
    -- jegliches Fachtabellen-Recht (kein ALL-TABLES-Grant unten).
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
        CREATE ROLE ops_readonly LOGIN PASSWORD 'ops_readonly'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
        CREATE ROLE ops_actions LOGIN PASSWORD 'ops_actions'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END$$;

GRANT USAGE ON SCHEMA public TO custode_app, custode_maint, ops_readonly, ops_actions;

-- Existing + future tables (created by the migration owner) are DML-accessible
-- to the app role; never DDL, never ownership.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO custode_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO custode_app;
