# CLAUDE.md — Modul `vault`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
End-to-End-verschlüsselter Tresor für Haushalts-Geheimnisse (KONZEPT §5). **Der Server sieht
ausschließlich Ciphertext** — er ver-/entschlüsselt **nie**. P7-S13 = Backend-Fundament (opakes
Storage + Schlüssel-Umschläge, ADR-0067). Krypto im Client (libsodium-wasm) = S14, Rotation/CSP = S15.

## Harte Sicherheitsregeln
- **Server kennt keinen Klartext, keine PII** — auch nicht den Namen eines Eintrags (der steckt
  verschlüsselt in `item_meta`). `wrapped_key`/`ciphertext` sind opake Base64-Strings, `wrap_meta`/
  `item_meta` opake Client-JSON-Blobs. **Nie** loggen, **nie** parsen, **nie** interpretieren.
- **Kinder & Gäste ausgeschlossen** (Root-CLAUDE.md): `require_role(Role.admin, Role.member)` — wie
  marketplace/capture. Kein Vault-Zugriff für Kinder, Punkt.
- **Kein Server-Backdoor:** verliert ein Haushalt alle Passphrasen **und** den Recovery-Code, ist der
  Haushaltsschlüssel unwiederbringlich. Gewollt.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „vault must not depend on other
  modules"). `vault.api` ist leer; Quermodul nur über `vault.*`-Events.
- Jede Fachzeile trägt `household_id`; RLS aktiv (`FORCE`), Negativtest je Tabelle.

## Datenobjekte (Migration 0051, ADR-0067)
- `vault_key_envelopes`: umschlossene Kopien des Haushaltsschlüssels. `kind` (passphrase|recovery),
  `member_id` (NULL bei recovery), `key_version`, `wrapped_key` (Base64), `wrap_meta` (JSONB opak).
  Partial-Unique: 1 passphrase je (member, version), 1 recovery je (household, version).
- `vault_items`: `ciphertext` (Base64), `item_meta` (JSONB opak), `key_version`, `author_id`,
  `version` = ETag.

## Schreibpfad
- Items: **online-first PATCH + If-Match** (ETag), Soft-Delete. Envelopes (PUT): Passphrase-Umschlag
  = idempotenter Upsert; **Recovery-Umschlag = write-once** (409 `vault_already_set_up`).

## Schnittstellen (HTTP, `/v1/vault`)
- `GET /keys` → eigene Passphrase-Umschläge + Haushalts-Recovery · `PUT /keys` (CSRF, Upsert).
- `GET /items` → Summary **ohne** `ciphertext` (Namen via `item_meta`) · `POST /items` (CSRF, 201,
  +ETag) · `GET /items/{id}` (+ETag, mit `ciphertext`) · `PATCH /items/{id}` (If-Match, CSRF) ·
  `DELETE /items/{id}` (CSRF, 204).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `vault.item_changed`, `vault.key_changed` → SSE-Entity `"vault"`.
- **abonniert:** —

## No-Gos
- **Niemals** serverseitig entschlüsseln, Klartext-Felder einführen oder Ciphertext/Meta loggen.
- Kein Klartext-Name/Label (auch der Titel ist Ciphertext in `item_meta`).
- Kinder/Gäste nie zulassen.
- **Den Recovery-Umschlag nie ersetzbar machen.** Der Server kann nicht prüfen, ob ein neuer
  Umschlag dasselbe `K_h` trägt — ein Ersetzen tauscht den Schlüssel unter allen anderen Mitgliedern
  aus (BUGLOG 2026-10-03). Rotation bekommt einen eigenen Pfad und ADR.
- `vault` importiert **kein** anderes Modul; Reaktion nur über `vault.*`-Events.
