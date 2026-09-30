#!/bin/sh
# Custode Postgres bootstrap fuer einen Produktionsserver (ADR-0020). Laeuft EINMALIG beim
# ersten Container-Init (leeres Volume), als Superuser (POSTGRES_USER).
#
# Im Gegensatz zur dev-Variante (infra/postgres/init.sql, hartcodierte
# Passwoerter) liest dieses Skript die Rollen-Passwoerter aus der Container-
# Umgebung — die echten Secrets stehen nur in <stack-dir>/.env, nie im Repo.
#
# custode_app: LOGIN, NOSUPERUSER, NOBYPASSRLS, besitzt nie Tabellen — eine
# vergessene WHERE-Klausel kann so nicht ueber Haushalte hinweg lecken (RLS ist
# die zweite Verteidigungslinie, ARCHITECTURE §9). Migrationen laufen als
# Owner (database_url_admin == POSTGRES_USER).
set -e

# Laut abbrechen statt Rollen mit leerem Passwort anzulegen. Greift nur beim FRISCHEN Init —
# ein bestehender Stack laeuft dieses Skript nie, dort werden die Rollen von Hand nachgezogen
# (docs/MANUAL_TESTS.md, Abschnitt A).
for _var in APP_DB_PASSWORD MAINT_DB_PASSWORD OPS_DB_PASSWORD OPS_ACTIONS_DB_PASSWORD; do
    eval "_val=\${$_var}"
    if [ -z "$_val" ]; then
        echo "init.prod.sh: $_var ist leer — in <stack-dir>/.env setzen (.env.prod.example)" >&2
        exit 1
    fi
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
        CREATE ROLE custode_app LOGIN PASSWORD '${APP_DB_PASSWORD}'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
        CREATE ROLE custode_maint LOGIN PASSWORD '${MAINT_DB_PASSWORD}'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    -- Betreiber-Konsole (ADR-0015/ADR-0071): liest NUR Aggregat-Views, nie Fachtabellen.
    -- ops_readonly = KPIs/Health; ops_actions = auditierte Aktions-Prozeduren (S8). Beide ohne
    -- jegliches Fachtabellen-Recht (kein ALL-TABLES-Grant unten) — das ist die Betreiber-Grenze
    -- auf DB-Ebene; ohne sie faellt die Konsole auf custode_app zurueck.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
        CREATE ROLE ops_readonly LOGIN PASSWORD '${OPS_DB_PASSWORD}'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
        CREATE ROLE ops_actions LOGIN PASSWORD '${OPS_ACTIONS_DB_PASSWORD}'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END\$\$;

GRANT USAGE ON SCHEMA public TO custode_app, custode_maint, ops_readonly, ops_actions;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO custode_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO custode_app;
EOSQL
