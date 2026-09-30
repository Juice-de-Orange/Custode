# Modul `guides`

**Status:** in Arbeit · **Phase:** 7 · **KONZEPT:** §5 (Anleitungen)

## Zweck & Verantwortung
Haushalts-**Anleitungen** (Markdown) mit **deutscher Volltextsuche**. P7-S6 ist das **Fundament**:
Titel + Markdown-Body + Kategorie + Tags, durchsuchbar per FTS. P7-S11 ergänzt einen
**Ansprechpartner** (`contact_id`). Anhänge und ACL (Sichtbarkeit je Anleitung) bauen in späteren
Slices darauf auf; `object_links` (Rezept↔Anleitung, Task↔Anleitung) ist das eigene Modul `links`
(P7-S8). Importiert **nur** `kernel/*`; kein Modul liest seine Tabellen.

## Datenobjekte (Migration 0047, ADR-0064)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `guides` | id; `author_id`; `title` (≤200); `body_md`; `category` (≤80); `tags text[]`; `contact_id` (nullable, nacktes Mitglieds-UUID, **kein FK**, Migration 0050); generierte `search_tsv` (deutsche FTS, GIN); `version` = ETag (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |

RLS-Negativtest (`test_guides_rls.py`: A↛B→0, WITH CHECK).

## Ansprechpartner (P7-S11, Migration 0050)
`contact_id` benennt optional ein Haushaltsmitglied als Ansprechperson — ein **nacktes UUID, kein FK**
auf accounts (Modulgrenze); der Anzeigename wird **clientseitig** über `GET /v1/household/members`
aufgelöst. PATCH unterscheidet „Feld fehlt" (unverändert) von `contact_id: null` (löschen) via
`model_fields_set` — nicht über einen None-Check. Web: Mitglieder-`<select>` im Anleitungs-Editor.

## Deutsche Volltextsuche (ADR-0064)
`search_tsv` ist eine **GENERATED**-Spalte `to_tsvector('german', title || ' ' || body_md)` (immutable,
+ GIN-Index). `GET /v1/guides?q=` sucht `search_tsv @@ plainto_tsquery('german', q)`, sortiert nach
`ts_rank` — mit deutschem Stemming (Query „Fahrrad" trifft „Fahrräder") und Stoppwörtern. Die DB pflegt
die Spalte automatisch; sie ist im ORM **nicht** gemappt (read-only, via `literal_column`).

## Schreibpfad
- **PATCH + If-Match** (ADR-0029): `version` (Trigger) = ETag; 412 stale, 428 fehlend. **Kein
  Sync-Batch** (online-first). Soft-Delete.

## Schnittstellen (HTTP, `/v1/guides`)
- `GET ?q=&category=` (member) → `list[GuideSummary]` (FTS-Suche ranked / Kategorie-Filter; sonst
  neueste Änderung).
- `POST` (member/admin, CSRF, 201) → `GuideResponse` (+ETag). `author_id` aus dem Principal.
- `GET {id}` (member, +ETag) · `PATCH {id}` (member/admin, If-Match, CSRF) · `DELETE {id}` (member/admin,
  CSRF, 204, Soft-Delete; **kaskadiert auf Anhänge** — Blob + Zeile).
- **Anhänge (P7-S22, Migration 0052, ADR-0069):** `GET {id}/attachments` (member, Metadaten) ·
  `POST {id}/attachments` (member/admin, multipart, CSRF; **503** ohne Storage, **413** > 25 MiB) ·
  `GET {id}/attachments/{aid}` (Download-Stream, `Content-Disposition`) · `DELETE {id}/attachments/{aid}`
  (member/admin, CSRF, 204). Tabelle `guide_attachments` (household-scoped, RLS+FORCE+Negativtest):
  **Bytes im Blob-Storage**, DB nur Metadaten + server-generierter `storage_key` (ADR-0033/0069).
- **Cross-Modul:** **keins** — `guides.api` ist leer; Reaktion über `guide.*`-Events.

## Events
- **publiziert:** `guide.created`, `guide.updated`, `guide.deleted` → SSE-Entity `"guides"`.
- **abonniert:** —

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /guides`, `GET /guides/{id}` | ✗ (401) | ✗ (403) | ✓ | RLS: nur eigene (404) |
| `POST/PATCH/DELETE /guides` | ✗ | ✗ (403) | ✓ | **RLS** |

## Web
Editor + FTS-Suche; das Detail bettet **Anhänge** (P7-S22, `AttachmentsPanel`: Upload, Liste mit
Download-Link, Löschen), den generischen **`LinksPanel`** und **`CommentThread`** ein.

## Tests
- `test_guides_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers), für `guides` **und**
  `guide_attachments`.
- `test_guides_http.py` — CRUD; **deutsche FTS** (Query „Fahrrad" trifft „Fahrräder", Body-Treffer,
  kein Treffer → leer); Kategorie-Filter; If-Match bumpt Version/stale→412; Löschen→404; fremd→404;
  **Ansprechpartner** setzen + explizit `null` löschen; **Anhänge** (Upload→Liste→Download→Löschen;
  503 ohne Storage; Löschen der Anleitung kaskadiert Blob+Zeile; fremder Haushalt → 404).

## Offene Punkte (spätere Slices)
- **ACL** (`acl_json`, Sichtbarkeit je Anleitung), Antivirus/Quota für Anhänge, Bild-Vorschau,
  Storage-Reaper verwaister Blobs, Markdown-Rendering, Trigram-/Fuzzy-Suche.
