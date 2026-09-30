# ADR-0033: Blob-Storage-Adapter + Foto-Normalisierung

- **Status:** beschlossen
- **Datum:** 2026-06-21
- **Betrifft:** `kernel/storage`, `kernel/images`, `modules/recipes` · **Bezug:** KONZEPT §5.2, ARCHITECTURE (Storage)

## Kontext

Rezepte sollen ein Foto haben (KONZEPT §5.2). Das wirft drei Fragen auf: **wo** die Bytes liegen, **wie**
sie hochgeladen werden und **was** mit Roh-Uploads passiert (Sicherheit/Datenschutz). Der Prod-Host
ist RAM-limitiert — ein zusätzlicher S3-Dienst (MinIO) wäre dort riskant.

## Entscheidung

- **Adapter statt fester Backend-Wahl:** `kernel/storage` definiert ein `Storage`-Protocol
  (`put`/`get`/`delete` + `enabled`). Implementierungen: **`FilesystemStorage`** (Dateien unter einem
  persistenten Volume — der Prod-Default, kein Extra-Dienst) und **`NullStorage`** (nichts
  konfiguriert → `enabled=False`, Upload sauber deaktiviert: **Graceful Enhancement**). S3/MinIO bleiben
  hinter demselben Protocol nachrüstbar. Auswahl via `settings.storage_dir` (`None` → Null).
- **Proxy-Upload, kein presigned URL:** Da der Default ein lokales Filesystem ist (kein S3), lädt der
  Client zur API (`PUT /v1/recipes/{id}/photo`, multipart); die API schreibt über den Adapter. Ein
  einziger Origin, keine CORS-/Bucket-Konfiguration. Server-generierte Keys (`recipe-{id}.jpg`) —
  niemals Client-Input → keine Path-Traversal.
- **Normalisierung beim Upload (`kernel/images`, Pillow):** jedes Bild wird **zu JPEG re-encodiert →
  strippt sämtliches EXIF (inkl. GPS = PII)**, Dimensionen werden gecappt; Nicht-Bilder → 422; 10-MiB-
  Roh-Cap. Foto-Bytes liegen im Blob-Storage, **nicht** in der DB (nur der `photo_key`).
- **Zugriff:** `GET …/photo` ist auth- + RLS-geschützt (nur Haushaltsmitglieder); die Web-`<img>`
  schickt das Session-Cookie mit. Kein öffentlicher Direktlink.

## Konsequenzen

- **Positiv:** läuft auf dem schlanken Host ohne Extra-Infra; EXIF-Strip schützt Standort-PII; das
  Feature ist überall **optional** (Null-Adapter); Backend swappable auf S3, falls später nötig.
- **Kosten:** Upload-Bytes laufen durch die API (kein Direkt-zu-S3) — für Haushaltsfotos vernachlässigbar.
  Das Volume braucht Backup wie die DB. Pillow als neue Dependency.

## Alternativen (verworfen)

- **MinIO auf dem Prod-Host** — S3-kompatibel + presigned URLs, aber RAM-hungrig auf einem knappen Host.
  Verworfen (Infra-Risiko); via Adapter später nachrüstbar.
- **Externes S3 (Cloud-Bucket)** — Kosten + externe Abhängigkeit + Credentials; für die aktuelle Stufe
  unnötig.
- **Bytes in Postgres (`bytea`)** — bläht DB/Backups/RLS-Zeilen auf; Blobs gehören nicht in die OLTP-DB.
