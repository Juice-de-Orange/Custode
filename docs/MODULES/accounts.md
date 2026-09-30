# Modul `accounts`

**Status:** in Arbeit · **Phase:** 1 · **KONZEPT:** §5.1

## Zweck & Verantwortung
Identität, Mitgliedschaft, Rollen, Einladungen. `users` ist globale Identität
(ein User ↔ n Haushalte); Haushalt/Mitgliedschaft/Einladung sind haushaltsgebunden.
Registrierung, Login und opaque Cookie-Sessions (Access in Redis, rotierender Refresh
mit Theft-Detection) sowie Haushalt-anlegen/einladen/beitreten/switch/Rollen sind über
`/v1/auth` und `/v1/household(s)` umgesetzt ([ADR-0021](../adr/0021-access-token-cookies-csrf.md)).

## Datenobjekte
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `users` | id (uuidv7), email unique | self (`app.user_id`) **oder** Mitbewohner des aktiven Haushalts; WITH CHECK nur eigene Zeile |
| `households` | id (uuidv7) | `id = app.household_id` |
| `memberships` | id; **unique (household_id, user_id)** | `household_id = app.household_id` |
| `invites` | id; code unique; expires_at | `household_id = app.household_id` |
| `consents` | id; **append-only** (app nur SELECT/INSERT) | `household_id = app.household_id` (USING + WITH CHECK) |

Alle Tabellen: `FORCE ROW LEVEL SECURITY`, `updated_at`/`version`-Trigger, `deleted_at`-Tombstone.
`custode_maint` hat **read-only** Cross-Haushalt-Zugriff für die Bootstrap-Lesepfade
(Login/Refresh-Lookup → `users`, Migration 0006; Invite-per-Code, eigene Haushalte listen,
Mitgliedschaft vor Switch prüfen → `households`/`memberships`/`invites`, Migration 0007).
Schreibvorgänge laufen immer als `custode_app`, gescopt auf den Ziel-Haushalt.

Auth-Audit `auth_login_events` (`kernel/auth`, Migration 0011) ist **user-scoped** (RLS
`user_id = app.user_id`, nicht haushaltsgebunden — Login ist pre-tenant; ADR-0025): je Login
ein Erfolg/Fehlschlag-Eintrag mit **nur `country_code`** (kein IP/E-Mail/Token); `custode_maint`
schreibt, der Nutzer liest seine eigenen Versuche; `user_id` NULL bei unbekannter E-Mail.

## Schnittstellen
- **HTTP `/v1/auth` (`router.py`):** `POST /register` (Auto-Login, 201) · `POST /login` ·
  `POST /refresh` (CSRF) · `POST /logout` (204, CSRF-frei, idempotent — beendet **Sitzung und
  Tokens**, unabhängig davon, welches Cookie ankommt; seit 11-B3 eine Funktion statt zweier
  Zweige, s. `accounts/CLAUDE.md`) · `GET /me` ·
  `POST /totp/setup|enable|disable|recovery-codes` (TOTP-2FA + Recovery-Codes, CSRF, ADR-0022);
  `login` akzeptiert `totp_code` ODER `recovery_code` (einmaliger Fallback) ·
  `POST /password/forgot` (immer 204, **keine Enumeration**) + `POST /password/reset` (Redis-Token,
  single-use, Passwort-Policy + HIBP, **revoked alle Sessions**; ADR-0027) ·
  `POST /email/verify/request` (auth, CSRF, resend) + `POST /email/verify/confirm` (Token →
  `email_verified_at`, single-use; Verifikations-Mail bei register).
- **HTTP `/v1/auth/passkeys` (WebAuthn, ADR-0023):** `register/begin|complete` (eingeloggt),
  `login/begin|complete` (passwortlos, discoverable), `GET`/`DELETE` (eigene verwalten).
- **HTTP `/v1/auth` Sessions/Audit (S8b):** `GET /sessions` (aktive Login-Familien, `current`-Flag
  via `Principal.family_id`) · `DELETE /sessions/{family_id}` (Remote-Logout, CSRF: `revoked_at`-
  UPDATE **plus** `access.revoke_access_family` in Redis; fremde/geratene id → 404) ·
  `GET /login-events` (eigene Anmeldeversuche, PII-frei). Alle **user-scoped** (RLS `user_id`).
- **HTTP `/v1/account` (`account_router`, S11):** `GET /profile` (Profil + `ETag` = `users.version`)
  + `PATCH /profile` (**If-Match**, CSRF; 412 stale / 428 fehlend; self-scoped). Profilfelder in
  `users.settings_json` (Migration 0014).
- **HTTP Kinder (S12, ADR-0028):** `POST /v1/household/children` (admin, CSRF — Kind anlegen +
  Eltern-Consent) · `POST /v1/auth/child-login` (pre-auth: household_id + Benutzername + 4-6-stelliger
  PIN → Session direkt im Haushalt; **ratenlimitiert** 5/15 min, constant-time).
- **HTTP `/v1` Haushalte:** `POST /households` (anlegen→admin) · `GET /households` (eigene) ·
  `POST /households/{id}/switch` · `POST /households/join` (Code) ·
  `POST /household/invites` (admin) · `GET /household/members` ·
  `PATCH /household/members/{membership_id}` (Rollenwechsel, admin) ·
  `DELETE /household/members/{membership_id}` (entfernen, admin) ·
  `POST /household/leave` (**jede Rolle**, CSRF — selbst gehen, s.u.) ·
  `POST /household/dissolve` + `GET /household/dissolve-preview` (**admin**, CSRF — Auflösung,
  ADR-0085) ·
  `GET /household/digest` + `PATCH /household/digest` (admin, CSRF) — Wochen-Digest
  pro Haushalt an-/abschalten (`settings_json['digest_enabled']`, Default an; P8-S7b).
- **Selbst-Austritt (Slice A):** `POST /v1/household/leave` trifft immer nur die aufrufende Person
  und braucht deshalb keine Berechtigung über die Mitgliedschaft hinaus — anders als
  `DELETE …/members/{id}`, das `AdminPrincipal` verlangt. Drei Abweisungen, alle 409 und alle nur
  relevant, wenn die Person Admin ist — plus `child_cannot_leave` für Kinder-Konten (ohne E-Mail
  und Passwort gibt es keinen Weg zurück; die Verwaltung entfernt sie stattdessen):
  `last_admin` (behebbar — jemand kann übernehmen),
  `only_children` (unbehebbar — niemand *kann*) und `sole_member` (**nur hier**: allein in einem
  Haushalt verlässt man ihn nicht, man löst ihn auf; die Kontolöschung lässt genau diesen Fall zu,
  weil es dort kein „stattdessen" gibt). Die Entscheidung teilen sich beide Pfade als reine
  Funktion `exit_blocker_reason` — zwei Fassungen liefen unweigerlich auseinander.
- **Haushalts-Auflösung (11-S1e, ADR-0085):** `POST /v1/household/dissolve` beendet den Haushalt
  für alle. Sie ist die Operation, die `sole_member` und `only_children` **auflöst** — beide
  verwiesen auf sie, und niemand konnte sie ausführen; bei `only_children` sperrte das eine Person
  aus ihrem Art.-17-Recht aus. Bestätigung durch **abgetippten Haushaltsnamen**, nicht
  `window.confirm`. Die Admin-Kontinuität wird hier **ausdrücklich freigegeben** (derselbe
  gesperrte Bestand, aber ohne `would_leave_no_admin`) — es ist die einzige Operation, die sie
  legitim beendet. **Kinder-Konten werden mit vorgemerkt**: sie haben kein Login außerhalb des
  Haushalts und wären sonst unerreichbar *und* von keinem Löschjob erfassbar. Das endgültige
  Ausräumen von **39 der 41** haushaltsgebundenen Tabellen (`audit_log` und `consents` bleiben) ist **Phase 2 (11-S1f, ADR-0086) und seit
  2026-08-02 gebaut**: Cron `purge_due_households_job` um 04:00, Menge zur Laufzeit aus dem Katalog
  abgeleitet, Reihenfolge aus `pg_constraint`, gelöscht als `custode_app` unter RLS und **je
  Mitglied** (zwei Tabellen sind mitglieds-gescopt). Der Code liegt am Composition Root
  (`app/household_purge.py` + `app/household_deletion_policy.py`), nicht im Modul.
- **Sessions:** opaque Cookie-Sessions (Access in Redis, Refresh rotierend in `auth_sessions`),
  Double-Submit-CSRF; Token-/Cookie-Design in [ADR-0021](../adr/0021-access-token-cookies-csrf.md).
- **Services (`api.py`):** `register_user`, `login`, `refresh`, `logout`,
  `create_household_with_admin`, `create_invite`, `accept_invite`, `change_role`,
  `remove_member`, `leave_household`, `dissolve_household`, `exit_blocker_reason`,
  `list_user_households`,
  `get_active_role`, `list_members`,
  `list_digest_recipients` (P8-S7, maint-Lese-Naht für den Wochen-Digest),
  `totp_begin_setup`, `totp_enable`, `totp_disable`, `generate_recovery_codes`,
  `consume_recovery_code`, `count_recovery_codes`, `passkey_register_begin`,
  `passkey_register_finish`, `passkey_auth_begin`, `passkey_auth_finish`,
  `list_passkeys`, `delete_passkey`, `list_active_sessions`, `revoke_session`, `list_login_events`,
  `request_password_reset`, `reset_password`, `send_verification_email`,
  `request_email_verification`, `confirm_email`, `get_profile`, `update_profile`, `create_child`,
  `child_login`.
- **Events out (live):** `member.joined` (Beitritt), `member.role_changed` (Rollenwechsel),
  `member.left` (Entfernen), `household.dissolved` (Auflösung — trägt die Ökonomie über **alle**
  Mitglieder in fester Reihenfolge, `app/household_dissolution.py`) — transactional outbox (`kernel/events/emit.py`), dispatcht vom
  Worker (`kernel/events/registry.py`, ARCHITECTURE §8.2).
- **`member.left` hat seit 11-S1a/b drei Abonnenten:** `calendar` (Feed-Token entwerten,
  CalDAV-Abos stilllegen), `wearables` (Art.-9-Daten hart löschen) und den Composition-Root-Ablauf
  `app/member_exit.py` (Escrow auflösen → Aufgaben freigeben → Restpunkte verfallen lassen, in
  **dieser** Reihenfolge). Die Sitzungen widerruft `remove_member` dagegen **synchron** — ein
  Access-Token ist bis zu 15 Minuten gültig, und `Principal` wird daraus gebaut, nicht aus der
  Datenbank.
- **Der Scope einer Sitzung wird je Rotation neu abgeleitet (11-S1g).** `POST /v1/auth/refresh`
  liest den zuletzt gewählten Haushalt aus Redis, behandelt ihn aber als **Hinweis**:
  `resolve_refresh_scope` → `get_active_role` entscheidet gegen die Datenbank (lebende
  Mitgliedschaft **und** lebender Haushalt), und die **Rolle aus dem Merkzettel wird verworfen**.
  Vorher schrieb die Rotation beides bis zu 30 Tage unbesehen fort — ein herabgestufter Admin blieb
  damit unbefristet Admin, weil `change_role` keine Sitzungen widerruft. `change_role` entwertet
  jetzt zusätzlich die **Access-Tokens** der betroffenen Person (nicht ihre Sitzungen: sie bleibt
  Mitglied), sodass die neue Rolle in einer Anfrage statt in fünfzehn Minuten greift.
  BUGLOG 2026-08-02.
- **Web-UI (Phase 1):** Login/Registrierung/Konto + **Security-Center `/security`** —
  TOTP-Setup mit QR + Passkey-Verwaltung über die bestehenden Endpunkte (kein Backend-Change;
  [ADR-0026](../adr/0026-qr-code-totp-setup.md)).
- **Ports:** Mail (`kernel/ports/mail.py`) — realer `adapters/smtp` (der SMTP-Anbieter des Betreibers, ADR-0027) bzw.
  Null/mailpit; gewählt im Composition-Root (`main.py` → `app.state.mail`), bezogen via `get_mail`.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member | admin | fremder Haushalt |
|---|---|---|---|---|---|
| `POST /v1/auth/register\|login` | ✓ | ✓ | ✓ | ✓ | — |
| `POST /v1/auth/password/forgot\|reset` | ✓ (öffentlich/Token) | ✓ | ✓ | ✓ | — |
| `POST /v1/auth/email/verify/request` | ✗ (401) | ✓ (eigenes Konto) | ✓ | ✓ | — |
| `POST /v1/auth/email/verify/confirm` | ✓ (Token) | ✓ | ✓ | ✓ | — |
| `GET\|PATCH /v1/account/profile` | ✗ (401) | ✓ (eigenes Konto) | ✓ | ✓ | — |
| `POST /v1/household/children` (Kind anlegen) | ✗ | ✗ (403) | ✗ (403) | ✓ | **immer ✗** (RLS) |
| `POST /v1/auth/child-login` | ✓ (PIN, rate-limited) | ✓ | ✓ | ✓ | — |
| `POST /v1/auth/refresh\|logout`, `GET /me` | ✗ (401) | ✓ | ✓ | ✓ | — |
| `POST /v1/auth/totp/setup\|enable\|disable\|recovery-codes` | ✗ (401) | ✓ (eigenes Konto) | ✓ | ✓ | — |
| `POST /v1/auth/passkeys/register/*` | ✗ (401) | ✓ (eigenes Konto) | ✓ | ✓ | — |
| `POST /v1/auth/passkeys/login/*` | ✓ (passwortlos) | ✓ | ✓ | ✓ | — |
| `GET\|DELETE /v1/auth/passkeys` | ✗ (401) | ✓ (eigene) | ✓ | ✓ | — |
| `GET /v1/auth/sessions\|login-events` | ✗ (401) | ✓ (eigene) | ✓ | ✓ | **RLS: nur eigene** |
| `DELETE /v1/auth/sessions/{family_id}` | ✗ (401) | ✓ (eigene) | ✓ | ✓ | **404 (RLS user-scoped)** |
| `POST /v1/households` (anlegen→admin) | ✗ | ✓ | ✓ | ✓ | — |
| `GET /v1/households` (eigene) | ✗ | ✓ | ✓ | ✓ | nur eigene |
| `POST /v1/households/{id}/switch` | ✗ | nur als Mitglied | ✓ | ✓ | ✗ (403) |
| `POST /v1/households/join` (Code) | ✗ | ✓ | ✓ | ✓ | — |
| `GET /v1/household/members` | ✗ | leer | ✓ | ✓ | **RLS: 0 Zeilen** |
| `POST /v1/household/invites` | ✗ | ✗ (403) | ✗ (403) | ✓ | **immer ✗** (RLS) |
| `PATCH /v1/household/members/{id}` | ✗ | ✗ (403) | ✗ (403) | ✓ | **immer ✗** (RLS) |
| `DELETE /v1/household/members/{id}` | ✗ | ✗ (403) | ✗ (403) | ✓ | **immer ✗** (RLS) |
| `POST /v1/household/dissolve` | ✗ (401) | ✗ (403) | ✗ (403) | ✓ (nur den eigenen; 422 bei falschem Namen, 409 wenn bereits aufgelöst) | **immer ✗** (RLS) |
| `GET /v1/household/dissolve-preview` | ✗ (401) | ✗ (403) | ✗ (403) | ✓ | **immer ✗** (RLS) |
| `POST /v1/household/leave` | ✗ (401) | ✗ (403, kein HH) | ✓ (eigene Mitgliedschaft) | ✓, sofern nicht letzter Admin (409) | **nur der aktive** (RLS) |
| `DELETE /v1/auth/account` | ✗ (401) | ✓ (eigenes Konto) | ✓ | ✓, sofern kein Haushalt aufhält (409) | — (cross-household über `maint`, nur eigene Zeilen) |
| `GET /v1/auth/account/deletion-blockers` | ✗ (401) | ✓ (leer) | ✓ | ✓ | — (nur eigene Mitgliedschaften) |

## Invarianten
- **Admin-Kontinuität:** ≥ 1 admin pro Haushalt; letzter Admin nicht herabstufbar
  (`would_leave_no_admin`, unit-getestet).
- **Ausstiegs-Blocker (Slice A):** `exit_blocker_reason` ist die **eine** Stelle, die entscheidet,
  ob ein Admin gehen darf — geteilt von `leave_household` und `account_deletion_blockers`.
  Tabellengetestet über alle Rollen-Kombinationen; `guest` zählt bewusst zu `only_children`, weil
  ein Gast die Verwaltung so wenig übernehmen kann wie ein Kind.
- Eindeutige `(household_id, user_id)`.
- **Kinder-Accounts (S12, ADR-0028):** `child`-User ohne E-Mail; `username` per Haushalt eindeutig
  (App-Check); PIN Argon2id-gehasht + ratenlimitiert; Eltern-Consent als `consents`-Zeile bei Anlage.

## Tests
- `test_accounts_service.py` — Admin-Kontinuität (pure, lokal).
- `test_cookies.py` / `test_csrf.py` — Cookie-Flags (dev/prod) + Double-Submit (pure, lokal).
- `test_totp.py` — RFC-6238-Vektoren + Drift-Fenster/Reject (pure, lokal).
- `test_accounts_rls.py` / `test_sessions_rls.py` — RLS-Negativtests (Testcontainers, CI); inkl.
  **`consents` (A↛B; S10)**.
- `test_flags.py` — Feature-Flag-Merge (pure, lokal): Property (Output-Keys==Default-Keys, Bool),
  Kinder-Default `marketplace_children=False`, Präzedenz `settings_json` > global (S10).
- `test_login_db.py` / `test_registration_db.py` — Login/Refresh/Logout + Registrierung (CI).
- `test_access_store.py` — opaque Redis-Access-Store (Testcontainers Redis, CI).
- `test_auth_http.py` — HTTP-E2E (PG+Redis, CI): Register/Login/Refresh-Rotation+Theft/
  Logout/CSRF + Haushalt anlegen/einladen/beitreten/switch/Rollen + RLS-Isolation +
  TOTP enroll→login-2FA→disable + Recovery-Code-Login (einmalig) + regenerate +
  Passkey register→passwortloser Login→delete (SoftWebauthnDevice) +
  **Sessions-Liste/`current`-Flag, Remote-Logout killt das andere Gerät, Cross-User-Revoke→404,
  Login-Events PII-frei + user-scoped (S8b)** + **Passwort-Reset (no-enum, single-use,
  Session-Revoke; S9a)** + **E-Mail-Verifikation (register→Mail, confirm→`email_verified`, Resend,
  ungültig/single-use; S9b)** + **Profil GET/PATCH-Roundtrip, If-Match-Konflikt (412) + -Pflicht
  (428) (S11)** + **Kinder: create→PIN-Login, falscher PIN (401), Rate-Limit-Lockout (429),
  admin-only (403), username-unique (409) (S12)**.
- `test_refresh_rescope.py` — **der Scope je Rotation** (PG+Redis, CI, 11-S1g, 10 Fälle): tote
  Mitgliedschaft → kein Scope · aufgelöster Haushalt → kein Scope (eigene Bedingung, eigener Test) ·
  Herabstufung wirkt ohne Sitzungs-Widerruf · Beförderung genauso · Merkzettel wird geräumt · ein
  Redis-**Lesefehler** räumt ihn dagegen **nicht** (sonst würde aus einer Störung ein dauerhafter
  Verlust) · kein Auto-Scope beim Rotieren · der **echte** `DELETE …/members/{id}` lässt gar nichts
  zu rotieren übrig · Gegenproben (unbeteiligtes Mitglied rotiert unverändert; nur die Tokens der
  betroffenen Person fallen). Jeder Fall zeigt erst das Vorher, und das Nachher als **Wirkung** —
  geprüft über eine RLS-gescopte Route, nicht über `/me` (das nur das Token zurückliest).
- `test_mail.py` — Mail-Adapter (pure, lokal): Null-No-Op, SMTP baut die Nachricht (gemocktes
  `aiosmtplib.send`), Fehler → `False` (ADR-0027).
- `test_accounts_events.py` — Domain-Events (`member.*`): Emit in der Fach-Tx, RLS-
  Haushalts-Scope, Rollback-Kopplung (fehlgeschlagener Join → kein Event), Join↔Event-
  Invariante (Testcontainers, CI).
- `test_login_events.py` — Login-Audit (Testcontainers): Erfolg/Fehlschlag/unbekannte E-Mail,
  RLS user-scoped (A↛B), PII-freie Spalten (ADR-0025).

## Offene Punkte
- TOTP-Härtung: Secret-Verschlüsselung at rest (ADR-0022 deferred); Recovery-Codes ✅.
- Passkeys (WebAuthn) ✅ (ADR-0023); RP-Allowlist als spätere Härtung.
- **E-Mail-Verifikation** ✅ (S9b, Migration 0012 `users.email_verified_at`, Verifikations-Mail bei
  Register, Banner + `/verify-email`-Confirm).
- **Kinder-Accounts (PIN-Login + Eltern-Consent)** ✅ (S12, ADR-0028). Die harte Modul-Sperre
  (Wearables/Vault) wird mit jenen Modulen wirksam (Flag-Default + `role=child` gesetzt).
- **Geräte-/Session-Liste + Remote-Logout + Login-Aktivität** ✅ (S8b, user-scoped Endpunkte auf
  `auth_sessions`/`auth_login_events`, ohne Migration).
