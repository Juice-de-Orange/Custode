# ADR-0048 — Einzel-Occurrence verschieben: Overrides als JSONB-Map in der Master-Zeile

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S10
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
P5-S5 erlaubt das **Absagen** einer Serien-Instanz (EXDATE). Es fehlt das **Verschieben** einer
einzelnen Occurrence („dieses eine Standup ausnahmsweise um 14:00"). RFC-5545 modelliert das als
separates VEVENT mit `RECURRENCE-ID`. Die Frage war die interne Repräsentation und wie viel Komplexität
in die Kern-Expansion fließt.

## Entscheidung
1. **Overrides als JSONB-Map auf der Master-Zeile** statt eigener Override-Events:
   `calendar_events.overrides` (Migration 0040, Default `{}`) bildet `{original_start_iso:
   {starts_at, ends_at}}` ab. Spiegelt das bestehende `exdates`-Muster (Mengen-Semantik in der
   Master-Zeile) — **keine** neuen Zeilen, also keine zusätzliche RLS-/Sichtbarkeits-/Owner-Logik und
   kein `series_id`/`recurrence_id`-Schema. Beim Expandieren ersetzt ein Treffer die rule-generierte
   Occurrence (`expand.py`), die Original-Instanz bleibt der Schlüssel.
2. **`expand_occurrences` liefert jetzt `(original_start, start, end)`.** Der `original_start` ist der
   stabile Cancel/Move-Schlüssel; `start`/`end` sind die effektiven (ggf. verschobenen) Zeiten. Die
   Belegungs-/Abwesenheits-Nähte nutzen nur `start`/`end`; `EventResponse` trägt zusätzlich
   `original_start`, damit das Web eine **verschobene** Instanz weiterhin per Original-Schlüssel
   absagen/zurücksetzen kann.
3. **Schreibpfad wie bei EXDATE** (ADR-0043): dedizierte POST-Actions `move-occurrence` /
   `reset-occurrence`, owner-only, ohne If-Match (Mengen-Semantik). 422 wenn die Original-Instanz keine
   echte Occurrence ist, abgesagt (EXDATE) ist, oder der neue Bereich invertiert ist.
4. **ICS-Feed konsistent.** Der Feed emittiert pro Override ein zusätzliches VEVENT mit gleicher UID +
   `RECURRENCE-ID` (Original-Instant) und der neuen `DTSTART`/`DTEND` — so übernimmt ein Abonnent die
   Verschiebung. (Die DTSTART bleibt in UTC; die separate VTIMEZONE-Frage aus ADR-0047 ist unberührt.)

## Konsequenzen
- **Positiv:** minimal-invasiv (eine additive Spalte, kein neues Entitäts-Modell); RLS/Sichtbarkeit
  unverändert; reine Expansion bleibt testbar; Feed bleibt konsistent; Move/Reset symmetrisch zu
  Cancel/Restore.
- **Abwägung / bewusst:** Eine Occurrence, die **aus** dem Abfragefenster heraus verschoben wurde,
  verschwindet aus der Liste (Overlap-Test auf der effektiven Zeit) — korrekt. Eine **in** das Fenster
  von außerhalb des Scan-Bereichs verschobene Instanz erscheint ggf. nicht (der Rule-Scan ist
  fensterbegrenzt); bei den üblichen kleinen Verschiebungen irrelevant, dokumentiert als Grenze.
- **Grenzen:** Overrides ändern nur Zeit (nicht Titel/Ort je Instanz) — pro-Instanz-Detailänderungen
  wären ein größeres Feature; hier bewusst nicht.

## Alternativen
- **Separate Override-Event-Zeilen (`series_id`/`recurrence_id`):** verworfen für S10 — verdoppelt
  Sichtbarkeits-/RLS-/Owner-Pfade und die Expansion müsste Master- und Override-Zeilen zusammenführen.
  Sinnvoll erst, wenn Overrides eigene Felder (Titel/Ort) tragen sollen.
- **Verschieben = Absagen + neues Einzel-Event:** verworfen — verliert den Serien-Bezug (Reset,
  Feed-RECURRENCE-ID) und verwaist Einzeltermine.
