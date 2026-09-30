# ADR-0067 — Vault: clientseitige E2E-Verschlüsselung, Server nur Ciphertext

**Status:** beschlossen (Backend-Fundament) · **Phase:** 7 (P7-S13) · **Datum:** 2026-06-24
**Kontext-KONZEPT:** §5 (Vault), Root-`CLAUDE.md` („Vault clientseitig verschlüsselt
(libsodium-wasm), Server sieht nur Ciphertext"), Roadmap Phase 7.

## Kontext
Der Vault speichert Geheimnisse (Passwörter, Codes, Dokumente) eines Haushalts. Harte Anforderung:
**Der Server sieht ausschließlich Ciphertext** — keine Klartext-Inhalte, keine PII, nie in Logs. Die
Ver-/Entschlüsselung passiert **vollständig im Client** (libsodium-wasm). Dieser Slice (S13) baut das
**Backend-Fundament** (opakes Ciphertext-Storage + Schlüssel-Umschläge). Die eigentliche Krypto
(Argon2id, Secretbox, Recovery) folgt im Web-Slice S14 — die konkreten Primitiv-Parameter werden dort
final festgelegt; das Backend bleibt **krypto-agnostisch** (es interpretiert keine der gespeicherten
Bytes).

## Entscheidung

### Schlüssel-Hierarchie (clientseitig, in S14 umgesetzt)
1. **Haushalts-Vault-Schlüssel** `K_h` — ein symmetrischer Schlüssel (geplant XChaCha20-Poly1305 /
   libsodium `secretbox`), mit dem **alle** Vault-Einträge des Haushalts verschlüsselt werden.
2. **Pro-Mitglied-Umschlag:** `K_h` wird mit einem aus der **Vault-Passphrase** des Mitglieds
   abgeleiteten Schlüssel verschlüsselt (KDF geplant **Argon2id**). Ergebnis = `wrapped_key` +
   `wrap_meta` (Salt, Nonce, KDF-Parameter — alles client-definiert).
3. **Recovery-Umschlag:** `K_h` wird zusätzlich mit einem hochentropen **Recovery-Code** verschlüsselt
   (haushaltsweit, ein Umschlag je `key_version`). So bleibt der Vault bei vergessener Passphrase
   wiederherstellbar.
4. **Schlüssel-Rotation** (Mitglied-Austritt, S15): neues `K_h` mit erhöhter `key_version`; Umschläge für
   verbleibende Mitglieder neu erzeugen; Einträge tragen die `key_version`, mit der sie verschlüsselt
   wurden (lazy/rolling Re-Encrypt möglich).

### Server-Speicherung (opak, dieser Slice)
- `vault_key_envelopes` — die **umschlossenen Kopien** von `K_h`: `member_id` (NULL = Recovery-Umschlag,
  haushaltsweit), `kind` (`passphrase`|`recovery`), `key_version`, `wrapped_key` (Base64-**Text**),
  `wrap_meta` (JSONB, **opak**: KDF-Algo/-Parameter, Salt, Nonce — client-definiert).
- `vault_items` — die Geheimnisse: `key_version`, `ciphertext` (Base64-Text), `item_meta` (JSONB, opak:
  Nonce, **verschlüsselter Name/Typ** — kein Klartext-Label!). `author_id`, `version` = ETag.
- **Base64-Text statt bytea:** JSON-freundlich, der Server behandelt die Felder als undurchsichtige
  Strings; er parst/interpretiert sie nie. Kein Klartext-Name → der Server kennt **nichts** über den
  Inhalt (auch nicht den Titel).

### Zugriff & Grenzen
- **Kinder & Gäste ausgeschlossen** (Root-`CLAUDE.md`: „keine Wearables/Vault für Kinder-Accounts") —
  `require_role(Role.admin, Role.member)`, exakt wie marketplace/capture.
- **RLS** `household_isolation` (USING + WITH CHECK) + FORCE je Tabelle; RLS-Negativtest.
- **Keine Inhalte/PII in Logs** — die Endpunkte loggen nie Ciphertext/`wrap_meta`/`item_meta`.
- `vault` importiert **nur** `kernel/*` (20. import-linter-Contract); `vault.api` leer.

## Konsequenzen
- **Plus:** Echtes E2E — selbst bei DB-Kompromittierung ist nichts ohne Passphrase/Recovery-Code lesbar.
  Der Server bleibt krypto-agnostisch; Primitiv-Wechsel (KDF/AEAD) brauchen **keine** Backend-Migration
  (alles in `wrap_meta`/`item_meta`).
- **Minus:** Server-seitige Suche/Sortierung über Inhalte ist **unmöglich** (alles Ciphertext) — gewollt.
  Klartext-Namen verboten → Listenansicht zeigt erst nach Client-Entschlüsselung Titel.
- **Minus:** Recovery/Reset ist eine reine Client-Zeremonie; verliert ein Haushalt **alle** Passphrasen
  **und** den Recovery-Code, ist `K_h` unwiederbringlich (kein Server-Backdoor — by design).
- **Offen (S14/S15):** libsodium-wasm-Integration, Passphrase-Setup/Unlock, Recovery-Code-Erzeugung,
  Rotation bei Austritt, CSP-Härtung.

## Umsetzung Web-Krypto (S14a)
Konkret gewählte Primitive (in `web/src/vault/crypto.ts`, libsodium-wasm dynamisch importiert):
- **KDF:** Argon2id (`crypto_pwhash`, `crypto_pwhash_ALG_ARGON2ID13`) mit `OPSLIMIT_INTERACTIVE`/
  `MEMLIMIT_INTERACTIVE` (Browser-tauglich, memory-hard); ops/mem + Salt liegen in `wrap_meta`, eine
  spätere Anhebung bleibt rückwärtskompatibel.
- **AEAD/Wrap:** `crypto_secretbox` (XSalsa20-Poly1305) für Schlüssel-Umschlag **und** Eintrags-
  Verschlüsselung; je Operation frischer Nonce (in `wrap_meta`/`item_meta`).
- **Name separat verschlüsselt:** `item_meta = {body_nonce, name_ct, name_nonce}`, `ciphertext` = Body
  — so entschlüsselt die Liste Titel ohne den Geheimnis-Body zu laden.
- **Recovery-Code:** base64-abgeleiteter hochentropischer Code (gruppiert), als zweiter Umschlag.

## Alternativen
- **Serverseitige Verschlüsselung (KMS):** Server könnte entschlüsseln → verletzt „Server sieht nur
  Ciphertext". Verworfen.
- **bytea statt Base64-Text:** spart ~33 % Speicher, aber multipart/Binär-Handling im JSON-API; der
  Mehrwert wiegt die Komplexität hier nicht auf. Base64-Text gewählt.
- **Klartext-Name + verschlüsselter Body:** erlaubte serverseitige Titel-Suche, leakt aber PII
  (Namen wie „Online-Banking SparkasseXY"). Verworfen — auch der Name ist Ciphertext.
