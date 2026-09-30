# ADR-0072 — Betreiber-Konsole: eigener Operator-Auth-Stack (Passwort + TOTP, Bearer-Session)

**Status:** beschlossen · **Phase:** 8 (P8-S7b) · **Datum:** 2026-06-29
**Kontext-KONZEPT:** `ARCHITECTURE` §8.6 (Backoffice: eigener Auth-Stack, Passkey+TOTP, `/ops`-Prefix),
§12 (Build-Info/Health), **ADR-0015** (Ops-Grenze), **ADR-0071** (Ops-DB-Fundament), §8.5 (Sessions).

## Kontext
Die Betreiber-Konsole braucht eine **von den Nutzern getrennte** Identität (KONZEPT: kein Haushalt,
eigener Stack). Die User-Auth (Cookie + Refresh-Rotation + RLS-Principal + Haushalt) passt nicht: ein
Operator hat keinen Haushalt und darf keine Fachzeile sehen. Außerdem dürfen Operator-Credentials nie
über die normale App-Rolle erreichbar sein.

## Entscheidung

### Eigene Tabelle `operators`, isoliert von `custode_app`
Migration 0056: `operators` (E-Mail, `password_hash`, `totp_secret`, `totp_enabled`, `is_active`) —
**kein** `household_id`, **keine** RLS (Mandantentrennung sinnlos). **`custode_app` wird per REVOKE
ausgesperrt** (entzieht den `ALTER DEFAULT PRIVILEGES`-Grant aus `init.sql`); nur `ops_readonly`
(Login-Lesen) und `ops_actions` (Verwaltung) erhalten Zugriff. Negativtest: `custode_app` →
`InsufficientPrivilege` auf `operators`.

### Auth = Passwort + Pflicht-TOTP, fail-closed
`authenticate_operator` prüft E-Mail + Passwort + **Pflicht-TOTP** (`totp_enabled` erzwungen) und
läuft auf der `ops_readonly`-Session. Jeder Fehlschlag → `None` (401); immer ein Passwort-Verify gegen
einen Dummy-Hash (konstante Zeit vs. Enumeration), gespiegelt vom Accounts-Login. **Passkey** ist in
ARCH §8.6 vorgesehen und folgt; TOTP ist v1-Pflicht.

### Opaque Bearer-Session in Redis (kein Cookie → keine CSRF-Fläche)
Login mintet ein opakes Token (`ops_session:<sha256>` in Redis, TTL `ops_session_ttl_s` = 8 h); nur der
Hash wird gespeichert (DB/Redis-Leak ergibt kein nutzbares Token). Der Client sendet
`Authorization: Bearer <token>`. Bewusst **kein** Cookie: die Konsole läuft auf eigenem
Prefix/Subdomain, ein Bearer-Header hat keine Ambient-Authority → CSRF entfällt.

### `ops_readonly`-DB-Verbindung
`get_ops_sessionmaker` (`database_url_ops`, Fallback app-URL nur in dev) — die `/ops`-Endpunkte lesen
ausschließlich über diese Rolle (Views + `operators`), nie über `custode_app`.

### Endpunkte (`/ops`)
`POST /ops/auth/login` · `POST /ops/auth/logout` (idempotent) · `GET /ops/me` ·
`GET /ops/health` (Build-Info env/version/git_sha, operator-only, `Cache-Control: no-store`).
KPI-Endpunkte (Aggregat-Views) = S7c; Support/Banner/Flags + auditierte Aktionen = S8.

## Konsequenzen
- **Plus:** vollständig getrennter Auth-Pfad; Operator-Credentials sind selbst bei einer App-SQLi nicht
  lesbar (Rollen-Isolation, DB-erzwungen). Wiederverwendet Passwort-/TOTP-/Token-Primitive des Kernels.
- **Plus:** Bearer statt Cookie → keine CSRF-/SameSite-Komplexität für `/ops`.
- **Minus:** Passkey + IP-Allowlist (ARCH §8.6) noch offen (Folge-Slices); v1 ist Passwort+TOTP.
- **Minus:** kein Operator-Self-Service/Recovery — Provisionierung per Seed/CLI (dokumentierter
  Follow-up); reale Credentials nie im Repo.
- **Offen (S7c/S8):** KPI-Endpunkte über die Views, Support-Suche, Banner, globale Flags, Aktions-
  Prozeduren über `ops_actions` mit `audit_log` + Haushalts-Transparenz-Log, Login-Audit/Rate-Limit.

## Alternativen
- **User-Auth wiederverwenden (Cookie/Principal/Haushalt):** erzwingt Haushalts-Kontext + RLS, die
  Operatoren nicht haben; vermischt zwei Identitätsräume. Verworfen.
- **Cookie-Session für `/ops`:** zusätzliche CSRF-/SameSite-Fläche ohne Mehrwert (eigene Subdomain).
  Verworfen zugunsten Bearer.
- **`custode_app` liest `operators`:** bricht die Credential-Isolation (App-Bug ⇒ Operator-Leak).
  Verworfen (REVOKE + eigene `ops_readonly`-Verbindung).
