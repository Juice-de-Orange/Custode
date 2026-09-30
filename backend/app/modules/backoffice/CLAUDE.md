# CLAUDE.md — Modul `backoffice` (Betreiber-Konsole)

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Betreiber-Konsole unter `/ops` (ARCH §8.6, ADR-0015). **Eigener Auth-Stack**, **kein** Haushalts-
Kontext, liest Haushaltsdaten **nur** über Aggregat-Views / definierte Aktions-Prozeduren — nie
Fachtabellen. P8-S7a = DB-Fundament (Views + Rollen). P8-S7b = Operator-Auth + `/ops`-Endpunkte.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „backoffice must not depend on
  other modules"). `backoffice.api` ist leer; kein Modul importiert `backoffice`.
- Läuft auf der **`ops_readonly`**-DB-Session (`get_ops_sessionmaker`) — kein Fachtabellen-Recht;
  liest die Aggregat-Views (S7c) + die `operators`-Auth-Tabelle.

## Auth (ADR-0015/ADR-0072)
- **Operatoren ≠ Nutzer:** eigene Tabelle `operators` (Migration 0056, **kein** `household_id`, keine
  RLS). `custode_app` darf sie **nie** lesen (REVOKE in 0056); nur `ops_readonly`/`ops_actions`.
- Login = E-Mail + Passwort + **Pflicht-TOTP** (Passkey folgt). Opaque **Bearer-Token** in Redis
  (`ops_session:*`, nur SHA-256-Hash gespeichert) — kein Cookie → **keine CSRF-Fläche**.
- Operator-Provisionierung = privilegiertes CLI, kein Self-Service:
  `python -m app.scripts.create_operator <email>` (P9). Läuft auf `ops_actions`, generiert Passwort
  **und** TOTP-Secret und gibt beides **einmalig** aus (die Konsole ist fail-closed auf TOTP —
  ohne Secret käme niemand rein), idempotent per E-Mail. Ohne die `ops_actions`-Rolle bricht es mit
  Exit 2 ab, statt auf `custode_app` zurückzufallen und die Betreiber-Grenze zu unterlaufen.
  Reale Credentials nie im Repo.

## Frontend (Konsument)
Die Konsole-UI ist ein **eigenes Web-Bundle** (`web/src/ops/`, Entry `web/index-ops.html`) auf einer
**eigenen Subdomain** mit **Bearer-Client** (kein Cookie/CSRF) — ADR-0074. Eigener Auth-Stack hier,
eigenes Bundle dort; keine Mitglieder-Cookies im Scope. Stand: Login + gewachte Konsole (S-OPS-FE-a),
**KPI-Dashboard** (Bestand/Neuanmeldungen/Build-Info aus `/ops/kpis`+`/ops/health`, S-OPS-FE-b),
**auditierte Banner + globale Flags** (S-OPS-FE-c), **Support-Suche + Feedback-Inbox** (S-OPS-FE-d),
**Audit-Log-Ansicht** (S-OPS-FE-g: Route `/audit`, read-only `GET /ops/audit` + client-seitiger
`action`-Filter).
Frontend damit vollständig; **Audit sensibler Reads ✅**, **Operator-Verwaltung im UI ✅** und
**Operator-Passkey (Backend + Frontend) ✅** (WebAuthn-Enrollment + passwortloser Login,
ADR-0072-Erweiterung). Das **Passkey-Frontend** (Enroll-View `/passkeys` + „Mit Passkey anmelden"
auf der Login-Seite) nutzt die reinen Ceremony-Helfer `web/src/auth/webauthn.ts` und den
`PasskeyManager` wieder; cookielos (flow_id im Body, kein Cookie). Damit ist die Betreiber-Konsole
vollständig.

## Operator-Passkey (ADR-0072-Erweiterung, Migration 0064)
- Tabelle `operator_passkeys` (FK `operators`, **keine RLS**; `custode_app` revoked, `ops_readonly` SELECT,
  `ops_actions` SELECT/INSERT/UPDATE/DELETE). Krypto = Kernel-Primitive `kernel/auth/webauthn.py` (py-webauthn).
- **Cookielos** (die Konsole hat kein Cookie/CSRF): Register-Challenge über den Bearer-Operator gekeyt
  (`ops_reg:{operator_id}`); passwortloser Login trägt eine opake single-use `flow_id` **im Body**
  (`ops_auth:{flow_id}`), nie ein Cookie. Login-Complete läuft auf `ops_actions` (Cross-Operator-Lookup +
  Sign-Count-Bump) und mintet den Bearer via `mint_ops_session`. Sign-Count-Monotonie + Origin/RP fail-closed.
- Endpunkte: `POST /ops/auth/passkeys/register/begin|complete`, `POST /ops/auth/passkeys/login/begin|complete`,
  `GET /ops/passkeys`, `DELETE /ops/passkeys/{id}` (nur eigene).

## Schnittstellen (HTTP, `/ops`)
- `POST /ops/auth/login` (E-Mail+Passwort+TOTP → Bearer; 401 fail-closed) ·
  `POST /ops/auth/logout` (revoke, idempotent 204) · `GET /ops/me` (Operator) ·
  `GET /ops/health` (Build-Info: env/version/git_sha, operator-only) ·
  `GET /ops/kpis` (Dashboard aus den Aggregat-Views: `usage_counters` + `daily_metrics`, P8-S7c) ·
  `GET /ops/banners` · `POST /ops/banners` · `POST /ops/banners/{id}/deactivate` (auditierte
  Banner-Verwaltung über `ops_actions` + `record_audit`, P8-S8b) ·
  `GET /ops/flags` · `PUT /ops/flags/{key}` (auditierte globale Feature-Flag-Verwaltung, P8-S8c;
  Tabelle `global_flags`, Auflösung in `accounts.me`) ·
  `GET /ops/households?q=` · `GET /ops/households/{id}` (Support-Suche, **nur Metadaten** aus der
  View `household_metadata`, ops_readonly, P8-S8d; **auditiert** `household.searched`/`.viewed`) ·
  `GET /ops/feedback` (Feedback-Inbox aus der View `ops_feedback`, ops_readonly, P8-S8e; **auditiert**
  `feedback.inbox.viewed`) ·
  `GET /ops/operators` (Liste, ops_readonly, **nur `OperatorSummary`** — nie password_hash/totp_secret) ·
  `POST /ops/operators/{id}/deactivate` / `/reactivate` (ops_actions, auditiert `operator.deactivated`/
  `.activated`; **409** bei Selbst- oder Letzter-Aktiver-Deaktivierung — Letztere per `FOR UPDATE`-Sperre
  race-fest; idempotent). **Anlegen bleibt CLI/Seed** (kein Self-Service). ·
  `GET /ops/audit?action=&limit=` (Audit-Trail-Ansicht, ops_readonly SELECT auf `audit_log`, P8-S5i-Read;
  neueste zuerst, optionaler Exact-`action`-Filter, `limit` 1–200; der Trail ist PII-frei per Konstruktion,
  daher wird **das Lesen selbst NICHT auditiert** — keine Rekursion). **Sensible Reads-Audit:** Lesen läuft auf `ops_readonly`, der Audit-Satz
  auf `ops_actions` (zweite Session, `record_audit`) — **kein PII im Detail** (nur Query-Länge/
  Trefferzahl/`household_id`/Kategorie), 404-Views werden nicht auditiert (Rollback vor dem Audit).
- **App-Anzeige (`/v1/banners`, separater Router):** `GET` aktive Banner (member, `custode_app`
  read-only) für die Banner-Leiste im Web-Shell.
- **Services (`api.py`):** leer.

## No-Gos
- **Nie** eine Fachtabelle lesen/schreiben — nur Aggregat-Views bzw. (S8) Aktions-Prozeduren.
- Kein Haushalts-Kontext, keine PII in KPIs/Logs. Operator-Credentials nie loggen/zurückgeben.
- Kein Self-Service-Operator-Signup; keine Operator-Tabelle für `custode_app` zugänglich.
