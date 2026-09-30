# Modul `backoffice` (Betreiber-Konsole)

**Status:** DB-Fundament (P8-S7a) + Operator-Auth & `/ops`-Endpunkte (P8-S7b). KPI-Endpunkte = S7c;
Support/Banner/Flags + Aktionen = S8.

**Zweck:** Betreiber-Sicht auf Kennzahlen/Health — **strikt getrennt** vom Fachbetrieb (ADR-0015):
liest **nur Aggregat-Views**, nie Fachtabellen, kein Haushalts-Kontext.

## Operator-Auth (P8-S7b, ADR-0072)
- Tabelle `operators` (Migration 0056): E-Mail + `password_hash` + `totp_secret`/`totp_enabled` +
  `is_active`. **Kein `household_id`, keine RLS.** `custode_app` per REVOKE ausgesperrt; nur
  `ops_readonly` (Login-Lesen) / `ops_actions` (Verwaltung).
- Login = E-Mail + Passwort + **Pflicht-TOTP** (`service.authenticate_operator`, fail-closed,
  konstante Zeit). Opaque **Bearer-Token** in Redis (`session.py`, `ops_session:*`, TTL 8 h) — kein
  Cookie, keine CSRF-Fläche. DB-Zugriff über `get_ops_sessionmaker` (`ops_readonly`).
- HTTP: `POST /ops/auth/login` · `POST /ops/auth/logout` (204, idempotent) · `GET /ops/me` ·
  `GET /ops/health` (Build-Info env/version/git_sha, operator-only) ·
  `GET /ops/kpis` (Dashboard aus `usage_counters` + `daily_metrics`, ops_readonly, P8-S7c) ·
  `GET/POST /ops/banners` + `POST /ops/banners/{id}/deactivate` (auditierte Banner-Verwaltung über
  `ops_actions` + `record_audit`, P8-S8b) · App: `GET /v1/banners` (aktive Banner, `custode_app`).

## Audited actions (P8-S8b, ADR-0073)
- `ops_banners` (Migration 0058, kein `household_id`): `custode_app` nur SELECT (Anzeige), Schreiben
  `ops_actions`-only. Jede Anlage/Deaktivierung schreibt einen `audit_log`-Eintrag (`record_audit`) in
  derselben Transaktion (`get_ops_actions_session` committet die Unit of Work).
- Web: ruhige Banner-Leiste im Shell (`web/src/routes/root.tsx`, `web/src/banners/queries.ts`).
- **Globale Feature-Flags (P8-S8c):** `global_flags` (Migration 0059, `custode_app` nur SELECT). Helfer
  `kernel/config/global_flags.py` (`load_global_flags`/`set_global_flag`). `GET /ops/flags` +
  `PUT /ops/flags/{key}` (auditiert, `flag.changed`, 422 bei unbekanntem Key). Aufgelöst als globale
  Ebene in `accounts.me` (`{**env, **db-overrides}`).
- **Audit sensibler Reads (P8-S8f, ADR-0073):** die Lesezugriffe `GET /ops/households` (Suche),
  `GET /ops/households/{id}` (Detail) und `GET /ops/feedback` (Inbox) schreiben `household.searched`/
  `household.viewed`/`feedback.inbox.viewed` in `audit_log`. Lesen bleibt `ops_readonly`; der Audit-Satz
  läuft auf einer zweiten `ops_actions`-Session (`record_audit`). **Kein PII im Detail** — nur
  Query-Länge/Trefferzahl/`household_id`/Kategorie; ein 404-Detail rollt vor dem Audit zurück (kein
  Phantom-Eintrag). Kein OpenAPI-Drift (Session per `Depends`, für das Schema unsichtbar).
- **Operator-Verwaltung im UI (P8-S8g):** `GET /ops/operators` (Liste, ops_readonly, `OperatorSummary` —
  **nie** password_hash/totp_secret) + `POST /ops/operators/{id}/deactivate|reactivate` (ops_actions,
  auditiert `operator.deactivated`/`.activated`, idempotent). Guards: **409** bei Selbst-Deaktivierung und
  bei der **letzten aktiven** Operator-Zeile (`SELECT … FOR UPDATE` serialisiert gleichzeitige
  Deaktivierungen → kein 0-aktiv-Lockout). **Anlegen bleibt CLI/Seed** — `python -m app.scripts.create_operator <email>` (ADR-0015): generiert Passwort + TOTP-Secret, gibt beides einmalig aus, idempotent per E-Mail, und bricht ohne `ops_actions`-Rolle bewusst ab, statt mit der falschen Rolle zu schreiben.
- `CurrentOperator`-Dependency (`dependencies.py`) löst den Bearer auf → 401 fail-closed.
- Provisionierung = CLI, kein Self-Service (s. o.); reale Credentials nie im Repo.
- Tests: `test_operators_auth.py` (Login+TOTP, /me, /health, Logout-Revoke, falsches TOTP/kein Token;
  Banner/Flag/Support/Feedback inkl. **Audit-Zähler** je auditiertem Read/Action);
  `test_ops_isolation.py` (custode_app ↛ `operators`).

## DB-Fundament (Migration 0055, ADR-0071)
- **Rollen** (`infra/postgres/init.sql`): `ops_readonly` (Lesen), `ops_actions` (Aktionen, S8) —
  `LOGIN NOSUPERUSER NOBYPASSRLS`, **ohne** Fachtabellen-Recht.
- **Aggregat-Views** (security definer, Owner `custode_maint` → aggregiert via `maint_all` über alle
  Haushalte):
  - `usage_counters` — Einzelzeile: `households`, `users`, `adult_members`, `children`.
  - `daily_metrics` — je Tag: `new_households`, `new_users` (Signup-Kurve).
  - `household_metadata` (Migration 0060, P8-S8d) — je Haushalt nur **Metadaten** (Name, Anlagedatum,
    Mitglieder-/Admin-Zahl) für die Support-Suche; **nie** Fachinhalte.
  - `ops_feedback` (Migration 0061, P8-S8e) — Feedback-Einsendungen für die Betreiber-Inbox
    (`GET /ops/feedback`); Feedback ist ein Kanal **an** den Support, daher über die View sichtbar.
- `ops_readonly` erhält **SELECT nur auf die Views**.

## Sicherheits-Gate
- `tests/test_ops_isolation.py` — `ops_readonly` liest die Views (korrekte Aggregate über alle
  Haushalte), aber `SELECT` auf `households`/`users`/`memberships` → `InsufficientPrivilege`.

## Offen
Nichts Fachliches mehr — die ehemals hier gelisteten Folge-Slices sind in Phase 8 gebaut:
`/ops`-Router mit eigenem Auth-Stack (`operators`, Passkey+TOTP, IP-Allowlist, ADR-0072),
Build-Info/Health, Support-Suche über den Fehler-Referenzcode, Banner, globale Feature-Flags und
die Aktions-Prozeduren über `ops_actions` mit `audit_log` + Haushalts-Transparenz-Log
(ADR-0071/0073/0074). **Operativ** gilt: `infra/postgres/init.prod.sh` legt die Ops-Rollen nur bei
leerem Volume an; auf einem Stack, dessen Volume älter ist, legt der Betreiber die Ops-Rollen und
den ersten Operator (`backend/app/scripts/create_operator.py`) von Hand an.

## No-Gos
- **Nie** eine Fachtabelle lesen/schreiben — nur Aggregat-Views bzw. (S8) definierte Aktions-Prozeduren.
- Kein Haushalts-Kontext, keine PII in KPIs/Logs.

## Tests
- `test_operators_auth.py` — Operator-Login mit Passwort + TOTP (Pflicht, fail-closed), opake
  Bearer-Session.
- `test_ops_isolation.py` — die Betreiber-Grenze: `ops_readonly` kommt an keine Fachtabelle.
- `test_audit_log.py` — append-only per Grant-Entzug (UPDATE/DELETE → `InsufficientPrivilege`).
- `test_create_operator_script.py` (P9) — das Provisioning-CLI: generiertes Passwort ist lang und
  einmalig, das TOTP-Secret verifiziert, und ohne `ops_actions`-Rolle **bricht das Skript ab**,
  statt auf `custode_app` zurückzufallen und die Betreiber-Grenze zu unterlaufen.
