# infra/

Lokale/produktive Infrastruktur-Bausteine.

- `postgres/init.sql` — Bootstrap der DB-Rollen (`custode_app` ohne BYPASSRLS/
  Ownership, `custode_maint`). Wird vom Compose-Postgres beim ersten Start
  ausgeführt. Migrationen laufen als Owner/Superuser (`database_url_admin`).
- `caddy/Caddyfile` — Reverse-Proxy für den **Produktiv**-Betrieb (statisches Web +
  API unter einer Origin, serviert HTTP `:80` hinter dem TLS-terminierenden Reverse-Proxy/
  Tunnel des Betreibers; ADR-0024). Im `web`-Service von `docker-compose.prod.yml` über das Caddy-
  Image gemountet. Im Dev nicht genutzt (Web läuft via `npm run dev`, proxyt `/v1`).

Der Dev-Stack wird über `docker-compose.dev.yml` (Repo-Wurzel) gestartet:
`make dev` → api, worker, postgres:18, redis, mailpit, radicale.
- `postgres/init.prod.sh` — Bootstrap der Prod-DB-Rollen beim **ersten** Container-Init
  (`custode_app`, `custode_maint`, `ops_readonly`, `ops_actions`; Passwoerter aus der Umgebung).
  Laeuft nur bei leerem Datenverzeichnis — auf einem bestehenden Stack die Rollen von Hand
  nachziehen (`docs/MANUAL_TESTS.md`, Vorbedingungen).
- `radicale/` — lokale CalDAV-Instanz fuer manuelles Testen und die Container-Tests
  (`test_calendar_sync_radicale.py`, `test_calendar_writeback_radicale.py`). Nicht produktiv.
