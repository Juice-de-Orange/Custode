# CLAUDE.md — Modul `guides`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Haushalts-Anleitungen (KONZEPT §5) mit deutscher Volltextsuche. P7-S6 = Fundament: Titel + Markdown +
Kategorie + Tags + FTS. P7-S11: **Ansprechpartner** (`contact_id`, optional). P7-S22: **Datei-Anhänge**
(`guide_attachments`, ADR-0069). ACL = späterer Slice; `object_links` ist eigenes Modul `links`.

## Ansprechpartner (P7-S11, Migration 0050)
- `contact_id` ist ein **nacktes Mitglieds-UUID, kein FK** auf accounts (Modulgrenze) — der Name wird
  **clientseitig** über `GET /v1/household/members` aufgelöst. Additive, nullable Spalte.
- PATCH unterscheidet „Feld fehlt" (unverändert) von „`contact_id: null`" (löschen) über
  `model_fields_set` — **nicht** über einen None-Check (sonst ließe sich der Kontakt nie entfernen).

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „guides must not depend on other
  modules"). Quermodul nur über Domain-Events (`guide.*`) — `guides.api` ist leer, kein Modul importiert
  `guides`.
- Jede Fachzeile (`guides`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest. `household_id`/
  `author_id` aus dem Principal/RLS.

## RLS (Migration 0047, ADR-0064)
- `guides`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger.
- Negativtest: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Deutsche FTS (ADR-0064)
- `search_tsv` ist eine **GENERATED** `to_tsvector('german', title || ' ' || body_md)` (immutable) +
  GIN-Index. Suche: `search_tsv @@ plainto_tsquery('german', q)`, `ts_rank`-sortiert. Spalte ist im ORM
  **nicht** gemappt (read-only via `literal_column("search_tsv")`) — **nie** versuchen sie zu schreiben.

## Schreibpfad
- **PATCH + If-Match** (ADR-0029): `version` (Trigger) = ETag; 412 stale, 428 fehlend. **Kein
  Sync-Batch** (online-first). Soft-Delete.

## Anhänge (P7-S22, Migration 0052, ADR-0069)
- `guide_attachments` (1:n, household-scoped, RLS+FORCE+Trigger, Negativtest): `guide_id` (nacktes
  UUID), `filename`, `content_type`, `byte_size`, `storage_key`, `uploaded_by`. **Bytes im
  Blob-Storage** (`kernel/storage`, ADR-0033), DB nur Metadaten; `storage_key` server-generiert + flach
  (`guide-attachment-{uuid}` → kein Traversal). **Graceful Enhancement:** Upload 503 ohne Storage.
- **Kaskade beim Löschen einer Anleitung im Service** (`delete_guide`): Blob entfernen + Zeile
  soft-deleten — **kein** DB-FK-Cascade (Soft-Delete-Muster).

## Schnittstellen (HTTP, `/v1/guides`)
- `GET ?q=&category=` (member) · `POST` (member/admin, CSRF, 201) · `GET {id}` (+ETag) ·
  `PATCH {id}` (member/admin, If-Match, CSRF) · `DELETE {id}` (member/admin, CSRF, 204).
- **Anhänge:** `GET {id}/attachments` (member) · `POST {id}/attachments` (member/admin, multipart,
  CSRF, 503/413) · `GET {id}/attachments/{aid}` (Download-Stream) · `DELETE {id}/attachments/{aid}`
  (member/admin, CSRF, 204).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `guide.created`, `guide.updated`, `guide.deleted` → SSE-Entity `"guides"`.
- **abonniert:** —

## No-Gos
- `search_tsv` **nie** im ORM schreiben (DB-generiert).
- `guides` importiert **kein** anderes Modul; Reaktion nur über `guide.*`-Events.
- Kein Sync-Batch + If-Match mischen (online-first → nur If-Match). Soft-Delete statt Hard-Delete.
