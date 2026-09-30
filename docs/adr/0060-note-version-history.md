# ADR-0060 — Notiz-Versions-Historie: Snapshot-vor-Edit, letzte 5

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S2
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5: Notizen führen eine **Versions-Historie (5 Versionen)** mit Wiederherstellen. P7-S1 hat das
Notiz-Fundament (PATCH + If-Match, `version` = ETag) gelegt. Zu entscheiden: Wo/wie werden alte Stände
gespeichert, wie viele, und wie funktioniert das Wiederherstellen.

## Entscheidung
1. **Eigene Tabelle `note_versions`** (Migration 0045, household-scoped, RLS USING+WITH CHECK + FORCE,
   RLS-Negativtest) — **append-only Snapshots** (kein Mixin/Trigger): `note_id`(FK CASCADE),
   `version_no`, `title`, `body_md`, `edited_by`, `created_at`. `version_no` = die Notiz-`version`, die
   der Snapshot **ablöst** (monoton, unique pro Notiz).
2. **Snapshot VOR dem Edit, nur bei Inhaltsänderung.** `update_note` archiviert den **aktuellen** Stand
   (`_snapshot_and_prune`) **bevor** es Titel/Body überschreibt — und **nur**, wenn Titel **oder** Body
   sich tatsächlich ändern. Ein reiner **Pin-Toggle** ist keine Inhaltsänderung und verbraucht **keinen**
   Versions-Slot.
3. **Kappung auf die letzten 5** beim Schreiben: nach dem Insert werden alle bis auf die 5 höchsten
   `version_no` der Notiz gelöscht. Deterministisch, kein Cron.
4. **Wiederherstellen ist selbst ein Edit:** `POST /v1/notes/{id}/restore?version_no=` archiviert
   zuerst den aktuellen Stand (Restore ist damit **rückgängig machbar**) und setzt dann Titel/Body aus
   dem Snapshot; bumpt die `version` (Trigger) und emittiert `note.updated`. 404 bei unbekannter Version.
5. **Lesen:** `GET /v1/notes/{id}/versions` (jedes Mitglied) → neueste zuerst, max 5.

## Konsequenzen
- **Positiv:** vollständige, RLS-isolierte Historie ohne Cron; „rückgängig"-fähiges Restore;
  deterministische Kappung; Pin-Toggle „verschwendet" keine Version; nutzt den bestehenden
  `version`-ETag als natürliche, monotone `version_no`.
- **Abwägung (E9):** Historie wird **vor** dem Edit geschrieben (Snapshot = alter Stand), nicht **nach**
  — so ist `version_no` lückenlos die abgelöste Version und der aktuelle Live-Stand steht **nicht**
  doppelt in der Historie. Bewusst; das Restore archiviert den Live-Stand explizit, damit nichts
  verloren geht.
- **Grenzen:** kein Diff/Blame, keine Autoren-Anzeige je Zeile (nur `edited_by` je Snapshot); kein
  „named checkpoint". Reine Text-Snapshots (für Notizen ausreichend; größere Inhalte/Anhänge = später).

## Alternativen
- **Snapshot NACH dem Edit** (neuer Stand archivieren): verworfen — dann steht der Live-Stand doppelt
  (Notiz + jüngste Version) und das erste Edit erzeugt keine „vorher"-Version; Snapshot-vor-Edit ist
  intuitiver („Historie = was war").
- **Versionen als JSONB-Array auf der Notiz:** verworfen — schlechter abfragbar, kein sauberer
  RLS-/Index-Pfad, Array-Mutation statt append-only Insert; eine Tabelle ist klarer.
- **Unbegrenzte Historie:** verworfen — KONZEPT nennt explizit „5 Versionen"; Kappung hält die Tabelle
  klein und die Semantik einfach.
