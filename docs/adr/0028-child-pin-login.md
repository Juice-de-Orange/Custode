# ADR-0028: Kinder-Accounts — Username + PIN-Login (Argon2id, ratenlimitiert)

- **Status:** beschlossen
- **Datum:** 2026-06-19
- **Betrifft:** `modules/accounts`, `kernel/auth` · **Bezug:** KONZEPT §5.1 (Kinder-Accounts), §8 (Authentifizierung), ADR-0021 (Sessions)

## Kontext

KONZEPT §5.1 fordert Kinder-Accounts: vom Admin angelegt, **ohne eigene E-Mail**, Login via
**Benutzername + PIN innerhalb des Haushalts-Kontexts**, **ratenlimitiert**, „ohne Wert außerhalb
der App". Ein PIN ist naturgemäß kurz (kindgerecht), also brute-force-anfällig, wenn nicht
gehasht + ratenlimitiert. Es braucht außerdem einen protokollierten **Eltern-Consent** (unter dem
AT-Einwilligungsalter) und die harten Schutzregeln (keine Wearables/Vault, Marketplace aus).

## Entscheidung

**Ein Kind ist ein normaler `User` (email/password NULL) mit einem household-uniquen `username` und
einem Argon2id-gehashten 4-6-stelligen PIN, plus eine `child`-Membership und eine `consents`-Zeile**
— alles in einer Transaktion (Migration **0015**: `users.username`, `users.pin_hash`).

- **Anlage** (`POST /v1/household/children`, admin, CSRF): eine `scoped_session(household_id,
  user_id=child_id)` erfüllt **gleichzeitig** die `users`-Self-Policy (`id = app.user_id`) und die
  household-Policies (Membership/Consent `household_id = app.household_id`). Eltern-Consent =
  `consents`-Zeile (`type="child_account"`, `granted_by=admin`, S10). `username` ist **per Haushalt
  eindeutig** (App-Check; ein globaler UNIQUE würde denselben Kindnamen über Haushalte verbieten).
- **Login** (`POST /v1/auth/child-login`, pre-auth): `household_id` + `username` + `pin`. Lookup
  cross-user als `custode_maint`; **constant-time** (Dummy-Hash gegen Username-Enumeration);
  **ratenlimitiert** über einen Redis-Counter (`kernel/auth/childpin.py`): 5 Fehlversuche → 15 min
  Lockout je `(household, username)`. Erfolg → Session, **direkt im Haushalt** (Access scoped +
  `role=child`, als aktiver Haushalt gemerkt). Der `household_id` reist im Login-Link
  (`/child-login?household=…`) — Kinder tippen keinen UUID.
- **Schutzregeln:** `role=child` + der Flag-Default `marketplace_children=False` (S10) greifen,
  sobald die Module (Wearables/Vault/Marketplace, Phase 2+) ihre Gates prüfen.

Der kurze PIN ist akzeptabel, weil er **Argon2id-gehasht at rest**, **ratenlimitiert** und
**household-gebunden** ist („ohne Wert außerhalb der App"). Kein neuer Auth-Mechanismus — wiederholt
Argon2id (`passwords.py`) + die Session-/maint-Bausteine (E8 „Boring Technology").

## Konsequenzen

- **Positiv:** keine eigene Kind-Identitätsschicht; wiederverwendet Hash/Session/RLS; Consent
  revisionssicher (append-only `consents`); Lockout begrenzt Brute-Force trotz kurzem PIN.
- **Negativ / Kosten:** niedrige PIN-Entropie (4-6 Ziffern) — durch Lockout + Hash + Haushalts-Scope
  mitigiert; `username`-Uniqueness app-seitig (kein DB-Constraint); die harte Modul-Sperre
  (Wearables/Vault) wird erst mit jenen Modulen wirksam (hier dokumentiert + Flag-Default gesetzt).
- **Auswirkungen:** Migration 0015 (additiv); Redis-Rate-Limit-Keys (kein PII — nur
  household+username); Tests: create→login, falscher PIN (401), **Lockout (429)**, admin-only (403),
  username-unique (409). AuthZ-Matrix + MODULES + CHANGELOG.

## Alternativen (verworfen, mit Begründung)

- **Eigene `child_credentials`-Tabelle** — mehr Komplexität; `User` + `role=child` + 2 Spalten
  genügen und halten Kinder im selben Identitäts-/Session-Modell. Verworfen.
- **PIN im Klartext / schwacher Hash** — inakzeptabel; ein DB-Leak gäbe alle PINs preis. Verworfen.
- **Globaler `username`-UNIQUE** — verböte denselben Kindnamen in verschiedenen Haushalten;
  Uniqueness gehört pro Haushalt. Verworfen (App-Check).
- **TOTP/Passkeys für Kinder** — zu schwer/gerätegebunden für Kinder; PIN ist der bewusst
  niedrigschwellige, haushaltsgebundene Pfad. Verworfen.
