# ADR-0020: Produktions-Deployment (Compose-Härtung statt dev-Defaults)

- **Status:** beschlossen
- **Datum:** 2026-06-15
- **Betrifft:** CD, Betrieb, Sicherheit · **Bezug:** ADR-0019 (CI/CD), ARCHITECTURE §14, KONZEPT §11 (Betrieb), CLAUDE.md (Mandanten-Isolation)

## Kontext

ADR-0019 aktivierte einen Deploy-Job, der **`docker-compose.dev.yml`** auf dem
Produktionsserver fährt — mit dem Vorbehalt „vor echten Nutzerdaten gehärtetes Compose".
Der Produktionsserver ist ein **geteilter, RAM-begrenzter VPS mit öffentlicher IP**, auf dem
weitere Dienste des Betreibers laufen, hinter einem TLS-terminierenden Reverse-Proxy/Tunnel.

`docker-compose.dev.yml` mappt Postgres (`5432`), Redis (`6379`), MinIO (`9000/9001`)
und Mailpit auf **0.0.0.0** und nutzt triviale Dev-Passwörter — auf einer Public-IP
wäre das eine **offene Datenbank im Internet**. Das verstößt direkt gegen die harte
Regel „Mandanten-Isolation / keine offenen DB-Ports".

## Entscheidung

1. **Eigenes `docker-compose.prod.yml`**. Eigenschaften:
   - **Keine veröffentlichten DB-/Cache-Ports.** Postgres & Redis nur im internen
     Compose-Netz. Nur die **API** lauscht auf **`127.0.0.1:8080`**, hinter
     dem Reverse-Proxy/Tunnel.
   - **Echte Secrets ausschließlich aus `<stack-dir>/.env`** (`--env-file`), nie im
     Repo (`.env*` ist in `.gitignore`). Vorlage: `.env.prod.example`.
   - **DB-Rollen-Passwörter aus der Umgebung**: `infra/postgres/init.prod.sh`
     ersetzt das hartcodierte `init.sql`; `custode_app` bleibt NOSUPERUSER/NOBYPASSRLS.
   - **RAM-Limits** je Service (Postgres 512M, Redis 128M, API 512M, Worker 512M),
     damit Custode die übrigen Dienste des Hosts nie verdrängt (OOM-Schutz).
   - **`restart: unless-stopped`**; **kein MinIO/Mailpit** (S3/SMTP optional — die App
     bootet ohne, Settings-Defaults).
2. **Deploy-Flow** (Actions-Job `deploy`, im privaten Betreiber-Repo): `git reset --hard
   origin/main` → `build` → `up -d postgres redis` → **`alembic upgrade head` als Owner** →
   `up -d api worker`. Migration vor App-Start (additive expand/contract).
3. **Schlüssel-Trennung:** dedizierter passwortloser **CI→Server**-Key (privat als
   GitHub-Secret, public in der `authorized_keys` des Servers) und ein
   **read-only Deploy-Key Server→GitHub** (`git pull`). Niemals der persönliche Schlüssel.
4. **Stufe 1 (dieser ADR):** Stack läuft intern, nur über einen privaten Zugangspfad
   erreichbar, Auto-Deploy aktiv.
5. **Stufe 2 (umgesetzt 2026-06-15):** öffentlich als `custode.example.com` über den
   **vorhandenen** TLS-terminierenden Reverse-Proxy/Tunnel des Betreibers. Kein zusätzlicher
   nginx, kein offener Host-Port; der Proxy terminiert TLS, uvicorn läuft mit
   `--proxy-headers`. Die Anbindung des Proxys an das Compose-Netz ist **Betreiber-Konfiguration
   außerhalb dieses Repos** und wird nur vom Betreiber geändert, nie vom Deploy-Automatismus
   (Härtungs-/Isolationsgrenze).

## Konsequenzen

- **Positiv:** Kein offener Daten-Port auf der Public-IP; Custode fügt sich
  konfliktfrei und ressourcenbegrenzt in den geteilten Host ein; jeder grüne `main`-Push
  deployt automatisch. Erfüllt die Mandanten-Isolations-Regel auch im Betrieb.
- **Negativ / Kosten:** Zwei zusätzliche Deploy-Keys + die zugehörigen GitHub-Secrets zu
  pflegen; `.env` lebt nur auf dem Server (Backup-Verantwortung des Betreibers).
- **Sicherheit:** `init.prod.sh` läuft nur bei leerem Volume — Passwortrotation
  später per `ALTER ROLE` (nicht durch Re-Init). DB/Redis sind ohne Host-Port nur
  aus dem Compose-Netz erreichbar.

## Alternativen (verworfen)

- **`docker-compose.dev.yml` weiternutzen** — offene DB auf Public-IP, untragbar.
- **Eine bestehende Postgres-Instanz des Hosts mitnutzen** — verletzt Isolation/Ownership,
  Custode braucht Postgres 18 (natives `uuidv7`).
- **Sofort öffentlich schalten** — unnötiger Eingriff in Domain/Proxy-Konfiguration des
  Betreibers vor erstem grünem Deploy; auf Stufe 2 verschoben.
