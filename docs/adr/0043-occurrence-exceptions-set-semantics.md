# ADR-0043 — Einzel-Occurrence-Ausnahmen als EXDATE-Menge ohne If-Match

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S5
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
RRULE-Serien (ADR-0041) wirken bislang nur ganzheitlich: Bearbeiten/Löschen trifft die **ganze
Serie**. Nutzer brauchen aber den häufigsten Einzelfall — *„dieser eine Termin fällt aus"* (z. B. ein
Meeting in einer Woche). RFC-5545 modelliert das mit **EXDATE** (eine abgesagte Occurrence) bzw.
einem RECURRENCE-ID-Override (eine **verschobene** Occurrence).

Zwei Entscheidungen waren zu treffen:
1. **Datenmodell** der Ausnahmen.
2. **Schreibpfad** — der Rest des Kalenders nutzt PATCH + If-Match (ADR-0034), und die Modul-Regel
   lautet „kein PATCH ohne If-Match".

## Entscheidung
1. **EXDATE als Mengen-Spalte.** `calendar_events.exdates timestamptz[]` (Migration 0036) hält die
   **Original-Startinstants** der abgesagten Einzeltermine. `expand.py` filtert Occurrences mit
   passendem Start (instant-genau, DST-sicher via UTC-Normalisierung); der ICS-Feed gibt sie als
   `EXDATE` mit, damit Abonnenten sie ebenfalls verwerfen. Diese Slice deckt **Absagen** (cancel) +
   **Rücknahme** (restore) ab. Das **Verschieben** einer Einzel-Occurrence (RECURRENCE-ID-Override)
   ist ein eigener späterer Slice — es braucht eine Override-Zeile mit Serien-Verweis und ist
   bewusst nicht hier vermengt.
2. **Mengen-Semantik statt If-Match.** Absagen = *Element zur EXDATE-Menge hinzufügen*, Rücknahme =
   *entfernen*. Beide Operationen sind **idempotent** (doppeltes Absagen = no-op) und
   **kommutativ** (Reihenfolge egal; zwei Mitglieder, die *verschiedene* Instanzen absagen, kollidieren
   inhaltlich nie). Darum laufen sie über **dedizierte POST-Action-Endpoints**
   (`/events/{id}/cancel-occurrence`, `/restore-occurrence`) **ohne If-Match** — analog zur
   LWW-pro-Feldgruppe-Logik des Sync-Batch. Der Versions-Trigger bumpt weiterhin (`version` = ETag),
   sodass paralleles **PATCH** auf andere Felder seine optimistische Sperre behält. So vermeiden wir
   spurious 412 bei nebenläufigen Absagen verschiedener Termine, ohne die Concurrency-Garantie des
   eigentlichen Event-Edits aufzugeben.

## Konsequenzen
- **Positiv:** häufigster Serien-Eingriff ohne Vor-GET (ein Round-Trip), kollisionsfrei bei parallelen
  Absagen, RFC-5545-konformer Feed (Google/Nextcloud droppen die Instanz), additive Migration.
- **Abwägung / bewusste Abweichung (E9):** Schreibpfad weicht von „PATCH + If-Match" ab — gerechtfertigt
  durch die echte Mengen-Semantik (idempotent + kommutativ). Eng begrenzt auf die EXDATE-Menge;
  jede andere Event-Mutation bleibt PATCH + If-Match.
- **Validierung:** `occurrence_start` muss eine **echte** Occurrence der Regel sein (`is_occurrence`,
  sonst 422); EXDATE auf eine Nicht-Serie → 422; owner-only (403 sonst); Sichtbarkeit/RLS unverändert.
- **Grenzen:** Verschieben/Override = späterer Slice; bis dahin ist „Absagen + neuen Einzeltermin
  anlegen" der Workaround.

## Alternativen
- **EXDATE in den RRULE-String mergen** (volles VEVENT-Parsing): verworfen — wir speichern nur die
  `RRULE`-Zeile; eine separate, explizite Spalte ist einfacher, reiner testbar und query-seitig klar.
- **If-Match auf cancel/restore:** verworfen — erzwingt Vor-GET und erzeugt spurious 412 bei
  nebenläufigen, inhaltlich konfliktfreien Absagen.
- **Separate `calendar_event_exceptions`-Tabelle:** für reine Absagen Overkill (eigene RLS, Joins);
  sinnvoll erst, wenn Overrides (verschobene Instanzen mit eigenen Feldern) dazukommen — dann als
  eigener Slice/ADR.
