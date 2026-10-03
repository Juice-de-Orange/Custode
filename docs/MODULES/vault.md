# Modul `vault`

**Status:** in Arbeit (Backend-Fundament) · **Phase:** 7 · **KONZEPT:** §5 (Vault)

## Zweck & Verantwortung
**End-to-End-verschlüsselter Tresor** für Haushalts-Geheimnisse (Passwörter, Codes, Dokumente). Harte
Regel: **Der Server sieht ausschließlich Ciphertext** — er ver-/entschlüsselt **nie**, loggt nie
Inhalte/PII. P7-S13 ist das **Backend-Fundament** (ADR-0067): opakes Ciphertext-Storage +
Schlüssel-Umschläge. Die Krypto (libsodium-wasm: Argon2id-Passphrase, Secretbox, Recovery-Code) folgt
im Web-Slice S14; Schlüssel-Rotation bei Austritt + CSP-Härtung in S15. Importiert **nur** `kernel/*`.

## Schlüssel-Hierarchie (clientseitig, ADR-0067)
1. **Haushalts-Vault-Schlüssel `K_h`** verschlüsselt alle Einträge.
2. **Pro-Mitglied-Umschlag:** `K_h` unter einem aus der Vault-Passphrase abgeleiteten Schlüssel
   (Argon2id) verschlüsselt → `vault_key_envelopes(kind='passphrase')`.
3. **Recovery-Umschlag:** `K_h` zusätzlich unter einem Recovery-Code → `kind='recovery'`,
   haushaltsweit (`member_id` NULL).
4. **Rotation** (S15): neues `K_h`, erhöhte `key_version`, Umschläge neu; Einträge tragen ihre
   `key_version`.

## Datenobjekte (Migration 0051, ADR-0067)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `vault_key_envelopes` | id; `member_id` (NULL ⇔ `kind='recovery'`, CHECK); `kind` ∈ {passphrase, recovery}; `key_version`; `wrapped_key` (Base64-Text, opak); `wrap_meta` (JSONB opak); `version` (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |
| `vault_items` | id; `author_id`; `key_version`; `ciphertext` (Base64-Text, opak); `item_meta` (JSONB opak, enthält verschlüsselten Namen); `version` = ETag | dito |

Partial-Unique-Indizes: 1 Passphrase-Umschlag je (household, member, key_version); 1 Recovery-Umschlag
je (household, key_version). RLS-Negativtest je Tabelle (`test_vault_rls.py`: A↛B→0, WITH CHECK).

## Server sieht nur Ciphertext (ADR-0067)
`wrapped_key`/`ciphertext` sind opake **Base64-Strings**; `wrap_meta`/`item_meta` opake Client-JSON
(KDF-Parameter/Salt/Nonce bzw. Nonce + verschlüsselter Name). Der Server **interpretiert nichts** —
kein Klartext, keine PII, **auch nicht der Eintrags-Name**. Folge: keine serverseitige Inhaltssuche
(gewollt). Die Listenansicht zeigt Titel erst nach Client-Entschlüsselung von `item_meta`.

## Zugriff & Schreibpfad
- **Kinder & Gäste ausgeschlossen** (Root-CLAUDE.md): member/admin only (`require_role`).
- Items: **online-first PATCH + If-Match** (ETag), Soft-Delete. Envelopes: PUT — der
  **Passphrase-Umschlag** ist ein idempotenter Upsert (je Mitglied/Version), der
  **Recovery-Umschlag ist write-once** (409 `vault_already_set_up`, ADR-0067-Nachtrag).
- `GET /items` liefert eine Summary **ohne** `ciphertext` (das Geheimnis wird erst beim Einzel-GET
  ausgeliefert) — minimiert die Exposition beim Listen-Laden.

## Schnittstellen (HTTP, `/v1/vault`)
- `GET /keys` (member/admin) → eigene Passphrase-Umschläge + Haushalts-Recovery-Umschlag.
- `PUT /keys` (member/admin, CSRF) → Passphrase-Umschlag: Upsert (idempotent je member/version).
  Recovery-Umschlag: nur anlegen; existiert einer, **409 `vault_already_set_up`** (ein
  byte-identischer Wiederholungsaufruf bleibt 200).
- `GET /items` → `list[VaultItemSummary]` (ohne ciphertext) · `POST /items` (CSRF, 201, +ETag) ·
  `GET /items/{id}` (+ETag, mit ciphertext) · `PATCH /items/{id}` (If-Match, CSRF) ·
  `DELETE /items/{id}` (CSRF, 204, Soft-Delete).
- **Cross-Modul:** **keins** — `vault.api` ist leer; Reaktion über `vault.*`-Events.

## Events
- **publiziert:** `vault.item_changed`, `vault.key_changed` → SSE-Entity `"vault"`.
- **abonniert:** —

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | Kind/Gast | member/admin | fremder Haushalt |
|---|---|---|---|---|---|
| alle `/v1/vault/*` | ✗ (401) | ✗ (403) | ✗ (403) | ✓ | RLS: nur eigene (404/leer) |

## Tests
- `test_vault_rls.py` — RLS-Negativ + WITH CHECK für **beide** Tabellen (Testcontainers).
- `test_vault_http.py` — Umschlag-Round-Trip (passphrase + recovery, idempotent); **Recovery-Umschlag
  write-once** (zweites Mitglied → 409, auch mit höherer `key_version`; Original unverändert;
  Gegenprobe: identischer Replay 200, eigener Passphrase-Umschlag 200); Item-CRUD mit
  ETag/If-Match (stale→412); Summary verbirgt `ciphertext`; **Kinder→403**; Haushalts-Isolation.
- Web: `vault-join.test.tsx` — Beitritt mit echter Krypto (dasselbe `K_h`, Recovery-Umschlag
  unberührt), Einrichten in der Reihenfolge recovery → passphrase, verlorenes Rennen, Kinder-Zustand.

## Web-Krypto (S14a, ADR-0067)
`web/src/vault/crypto.ts` (libsodium-wasm, **dynamisch importiert** → Lazy-Chunk): Argon2id
(`crypto_pwhash`, INTERACTIVE) leitet aus Passphrase/Recovery-Code einen Wrap-Key ab;
`crypto_secretbox` (XSalsa20-Poly1305) umschließt den Haushaltsschlüssel und verschlüsselt Einträge.
Der Name wird **separat** verschlüsselt (in `item_meta`), damit die Liste Titel ohne den Geheimnis-Body
entschlüsseln kann. `vault/queries.ts` kapselt die HTTP-Endpunkte (Items mit ETag/If-Match).
Krypto-Round-Trip-Unit-Tests in `web/src/test/vault-crypto.test.ts`.

## Vault-Route-UI (S14b)
`/vault` (`web/src/routes/vault.tsx`): **Einrichten** (Passphrase setzen → Schlüssel erzeugen +
Passphrase- & Recovery-Umschlag speichern, Recovery-Code **einmalig** angezeigt), **Entsperren**
(Passphrase, falscher → Fehler), **Einträge** anlegen (Name + Geheimnis clientseitig verschlüsselt),
auflisten (Namen je Eintrag entschlüsselt), aufklappen (Geheimnis-Body on-demand entschlüsselt),
löschen. Der Haushaltsschlüssel lebt **nur im Speicher** (Reload → erneut entsperren). libsodium-wasm
ist ein **separater Lazy-Chunk** (nur auf der Vault-Route geladen). Nav-Link, i18n DE/EN.

## Beitritt weiterer Mitglieder (ADR-0067-Nachtrag 2026-10-03)
Hat der Haushalt bereits einen Recovery-Umschlag und das Mitglied noch keinen eigenen
Passphrase-Umschlag, zeigt `/vault` **„Tresor beitreten"** statt „Tresor einrichten": das Mitglied
gibt den **Wiederherstellungs-Code des Haushalts** ein, der Client entpackt `K_h` aus dem
Recovery-Umschlag und packt **dasselbe** `K_h` unter die eigene Passphrase. Es entsteht kein neues
`K_h`, der Recovery-Umschlag wird nie geschrieben. Das ist eine Zwischenlösung im bestehenden
Umschlagmodell; der Public-Key-Beitritt aus KONZEPT §5.11 braucht die asymmetrische
Pro-Mitglied-Identität (siehe „Offene Punkte"). Kinder und Gäste sehen auf `/vault` „nicht
verfügbar" statt eines Fehlers; die Schlüssel werden für sie gar nicht abgefragt.

## Recovery + Passphrase-Wechsel (S15a)
„Passphrase vergessen?" entsperrt den Tresor clientseitig über den **Recovery-Umschlag** (Recovery-Code
statt Passphrase; falscher Code → Fehler). Nach dem Recovery-Entsperren fordert die UI das Setzen einer
**neuen Passphrase**; ein Passphrase-Wechsel ist zudem jederzeit im entsperrten Tresor möglich
(`ChangePassphrase`: re-wrappt den im Speicher liegenden Haushaltsschlüssel → `PUT /v1/vault/keys`).

## CSP-/Security-Header (S15b)
Der Caddy-Reverse-Proxy (`infra/caddy/Caddyfile`) setzt für die SPA `X-Content-Type-Options`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, restriktive `Permissions-Policy` (erzwingend)
und eine **CSP im Report-Only-Modus** (nicht-brechend: `script-src 'self' 'wasm-unsafe-eval'`,
`connect-src 'self'` für same-origin SSE/API). Erzwingung folgt nach Produktions-Beobachtung.

## Einträge bearbeiten (S16)
Ein aufgeklappter Eintrag lässt sich **inline bearbeiten**: Name + Body werden clientseitig neu
verschlüsselt und per `PATCH /v1/vault/items/{id}` + **If-Match** (ETag des geladenen Eintrags)
gespeichert (412 bei zwischenzeitlicher Änderung). Damit ist die Item-CRUD vollständig.

## Offene Punkte (spätere Slices)
- **Public-Key-Beitritt und Recovery-Code pro Mitglied** (KONZEPT §5.11) — bis dahin ist der
  Recovery-Code ein haushaltsweit geteiltes, nicht wechselbares Geheimnis (ADR-0067-Nachtrag).
- **Schlüssel-Rotation** bei Mitglied-Austritt (neue `key_version`, Re-Wrap/Re-Encrypt — braucht
  asymmetrische Pro-Mitglied-Identität, eigener ADR).
