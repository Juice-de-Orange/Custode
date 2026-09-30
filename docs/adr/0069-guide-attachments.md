# ADR-0069 — Anleitungen: Datei-Anhänge (Bytes im Blob-Storage, Metadaten in der DB)

**Status:** beschlossen · **Phase:** 7 (P7-S22) · **Datum:** 2026-06-24
**Kontext-KONZEPT:** §5 (Anleitungen: „Markdown, Anhänge, Kategorien, FTS, ACL, Ansprechpartner"),
Root-`CLAUDE.md` (Graceful Enhancement, Modulgrenzen), Roadmap Phase 7. Baut auf **ADR-0033**
(Rezept-Fotos: Bytes im Blob-Storage, nur Key in der DB) auf.

## Kontext
Anleitungen (`guides`) sollen Dateien tragen können (Handbücher, Garantiescheine, Fotos). Anders als
das **eine** Rezept-Foto (`photo_key`-Spalte) sind das **mehrere** Anhänge pro Anleitung. Wie bei den
Fotos sollen die **Bytes nie in die DB**, sondern in den pluggbaren Blob-Storage (`kernel/storage`,
Filesystem auf dem Single-Host, S3/MinIO später).

## Entscheidung

### Eigene Tabelle `guide_attachments` (Migration 0052)
Eine 1:n-Tabelle (Anleitung → Anhänge), household-scoped wie jede Fachtabelle:
`guide_id` (nacktes Modul-internes UUID), `filename`, `content_type`, `byte_size`, `storage_key`
(server-generiert), `uploaded_by` (+ Standard-Mixin). RLS `household_isolation` (USING + WITH CHECK)
+ FORCE + Versions-Trigger + GRANT; **RLS-Negativtest** je Tabelle (A↛B → 0, WITH-CHECK-Verstoß).

### Bytes im Blob-Storage, Key server-generiert
- `storage_key = "guide-attachment-{uuid}"` — **flach** (der Filesystem-Backend behält nur das letzte
  Pfad-Segment → kein Path-Traversal) und über die Attachment-UUID eindeutig, ohne Haushalt/Anleitung
  zu leaken. Die DB kennt **nur** Metadaten; die Bytes liegen im Storage.
- **Graceful Enhancement:** ist kein Storage konfiguriert (Null-Adapter), liefert der Upload **503**
  (wie Rezept-Fotos). Lese-/Listen-Pfade funktionieren ohne Storage (zeigen nur Metadaten; der
  Download 404t, wenn der Blob fehlt).

### Kaskade beim Löschen = im Service (Soft-Delete + Blob-Entfernung)
- Kein DB-FK-`ON DELETE CASCADE`: Anleitungen werden **soft-deletet** (Tombstone), ein harter
  FK-Cascade passt nicht dazu. `delete_guide` räumt daher die Anhänge **im Service** auf — Blob aus dem
  Storage entfernen **und** die Zeile soft-deleten. (Konsistent mit dem P7-S20-Reaper-Prinzip, hier
  aber modul-intern, da Anhänge zu `guides` gehören.)

### HTTP (`/v1/guides/{id}/attachments`)
- `GET` (Liste, Metadaten) · `POST` (multipart, member/admin, CSRF, 503 ohne Storage, 413 zu groß,
  25 MiB-Cap) · `GET /{aid}` (Download-Stream, `Content-Disposition: attachment`) ·
  `DELETE /{aid}` (member/admin, CSRF, 204). Dateiname wird **saniert** (Path-/Control-Chars,
  Header-Injection). Download per cookie-authentifiziertem Direktlink im Web.

## Konsequenzen
- **Plus:** Wiederverwendet das etablierte Storage-Port-Muster (ADR-0033); Backend-Wechsel (S3) braucht
  **keine** Schema-Migration. Saubere 1:n-Modellierung, RLS-isoliert, kein Cross-Modul-Import.
- **Plus:** Voll graceful — ohne Storage bleibt die Anleitung nutzbar, nur Uploads sind aus.
- **Minus:** Keine Server-seitige Virenprüfung/Inhaltsvalidierung in diesem Slice (nur Größen-Cap +
  Dateiname-Sanitisierung) — Antivirus/Quota = spätere Slices.
- **Minus:** Verwaiste Blobs sind möglich, falls der Storage-Delete scheitert, während die DB-Tx
  committet (best-effort `_remove_blob`); ein Storage-Reaper (Keys ohne lebende Zeile) ist ein
  späterer Slice.
- **Offen:** ACL (wer darf welche Anleitung/Anhänge sehen), Bild-Vorschau/Thumbnails, Quota je
  Haushalt, Anhänge auch an Briefen (gleicher Mechanismus).

## Alternativen
- **Bytes in der DB (`bytea`):** bläht die DB/Backups auf, sprengt Row-Limits; verworfen (ADR-0033).
- **`photo_key`-artige Einzelspalte an `guides`:** erlaubt nur **einen** Anhang; verworfen (Anhänge
  sind n).
- **Harter FK mit `ON DELETE CASCADE`:** unverträglich mit dem Soft-Delete-Muster; Kaskade im Service.
