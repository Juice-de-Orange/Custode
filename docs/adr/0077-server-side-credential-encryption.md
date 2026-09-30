# ADR-0077 — Server-seitige Credential-Verschlüsselung (`kernel/crypto`, Fernet)

**Status:** beschlossen · **Phase:** 9 (9-S1) · **Datum:** 2026-07-08
**Kontext-KONZEPT:** §5.11 (CalDAV-Abos: `creds_enc`), §5.15 (Wearables: `tokens_enc`),
§10 (Sicherheit), `ARCHITECTURE` §8.3 (Ports & Adapter), ADR-0067 (Vault = clientseitig E2E).
Roadmap Phase 9 (CalDAV-Zwei-Wege-Abos, Oura OAuth2).

## Kontext
Phase 9 speichert erstmals Fremd-Credentials, die der **Server selbst benutzen** muss:
das App-Passwort eines CalDAV-Abos (der Sync-Worker authentifiziert sich damit alle
15 min) und die Oura-OAuth-Tokens (der Nacht-Pull refresht und verwendet sie). Damit
scheiden beide bestehenden Muster aus:

- **Vault (ADR-0067)** ist clientseitig E2E — der Server sieht nur Ciphertext und kann
  damit nichts anfangen. Für Worker-Credentials unbrauchbar.
- **Hashing** (Passwörter, Refresh-/Ops-Tokens) ist Einweg — der Klartext muss aber
  wiederherstellbar sein.

Klartext in der DB wäre das Gegenteil der Projektlinie (RLS schützt vor Mandanten-,
nicht vor Infrastruktur-Lecks: Backups, Dumps, ein kompromittiertes `psql`).

## Entscheidung

### `kernel/crypto/secretbox.py` — Fernet mit Schema-Präfix
- **Fernet** aus `cryptography` (AES-128-CBC + HMAC-SHA256, authentifiziert, random IV,
  urlsafe-Tokens). `cryptography` war bereits transitive Abhängigkeit (py-webauthn) und
  wird direkte Dependency. Kein Eigenbau, kein zusätzliches Paket (libsodium bleibt dem
  Web-Vault vorbehalten).
- Gespeichertes Format: **`v1:<fernet-token>`**. Der Schema-Präfix macht Algorithmus-
  oder Key-Rotation erkennbar (Re-Wrap-Job kann `v1:`-Zeilen umschlüsseln, neue Schemata
  laufen parallel an).
- **Key:** `CUSTODE_CRYPTO_KEY` (Fernet-Key, urlsafe-Base64). Erzeugung über den
  Ops-Helfer `app.kernel.crypto.generate_key()`. Lebt ausschließlich in der Deployment-
  `.env` (auf dem Server, chmod 600) — nie im Repo, nie in der DB, nie in Logs.
- **Graceful Enhancement:** ohne Key liefert `get_secretbox()` `None` → Factories wählen
  Null-Adapter, Endpunkte antworten **503** über `require_secretbox()` (dasselbe Muster
  wie Blob-Storage ohne Backend). Kein Crash, App bleibt vollwertig ohne die Integrationen.
- **Fehlerverhalten:** Manipulation/falscher Key/unbekanntes Schema → `SecretBoxError`
  ohne Payload-Details (Ciphertext kann angreiferkontrolliert sein); malformter Key
  schlägt **beim Komposieren** fehl (fail loud), nicht beim ersten Encrypt.

### Bewusste Abgrenzungen
- **Kein AAD/Row-Binding** (AES-GCM mit Kontext-AAD): schützt nur gegen Angreifer mit
  DB-Schreibzugriff — die sind außerhalb des Bedrohungsmodells dieser Stufe (dann sind
  auch Outbox/Ledger manipulierbar). Fernet-Einfachheit gewinnt; bei Bedarf ist `v2:`
  mit AAD durch den Präfix vorbereitet.
- **Kein KMS/HSM:** ein Ein-Server-Deployment hat keinen getrennten
  Vertrauensanker; die `.env` ist dort die bestehende Secret-Grenze (wie SMTP/GitHub).
- **Key-Rotation v1 = dokumentierter Handgriff:** neuen Key setzen, Re-Wrap-Skript
  (liest `v1:` mit altem, schreibt mit neuem) — als auditiertes ops-CLI, wenn erstmals
  nötig. `MultiFernet` hält die Tür offen.

## Konsequenzen
- CalDAV-`creds_enc` (9-S2) und Oura-`tokens_enc` (9-S6) speichern ausschließlich
  `SecretBox`-Werte; Klartext existiert nur im Prozess-Speicher des Workers/Requests.
- Betreiber-Handgriff vor 9-S2-Nutzung: `CUSTODE_CRYPTO_KEY` erzeugen und auf dem Server
  in `<stack-dir>/.env` legen (dokumentiert in `docs/` + CHANGELOG; ohne Key bleiben
  die Features sichtbar aus/503).
  **Nachtrag 2026-07-26:** Die `.env` allein genügt nicht — `--env-file` wirkt nur auf die
  Compose-Interpolation. Der Schlüssel muss zusätzlich in den `environment:`-Blöcken **aller**
  Services stehen, die ihn lesen (`api`, `worker`, `scheduler`; der Worker fährt den
  CalDAV-Cron). Genau das war vergessen worden — der Regressionstest
  `backend/tests/test_compose_env.py` erzwingt es jetzt, s. BUGLOG 2026-07-26.
- Tests: reine Unit-Suite (Roundtrip, Unicode, Nichtdeterminismus, Manipulation,
  falscher Key, Schema, fehlender Key → None/503) — läuft ohne Docker, auch lokal.
