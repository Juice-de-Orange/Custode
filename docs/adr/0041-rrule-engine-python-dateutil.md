# ADR-0041: RRULE-Engine — `python-dateutil` statt Eigenbau

- **Status:** beschlossen
- **Datum:** 2026-06-24
- **Betrifft:** `modules/calendar` · **Bezug:** KONZEPT §5.11, Roadmap Phase 5, Tabu „Neue Technologie nur mit ADR ‚Bestehendes scheitert nachweislich an X'"
- **Phase/Slice:** P5-S2

## Kontext

Wiederkehrende Kalender-Events (KONZEPT §5.11) brauchen **RFC-5545-Recurrence-Rules** (`RRULE`):
`FREQ=WEEKLY;BYDAY=MO,WE`, `INTERVAL`, `COUNT`, `UNTIL`, `BYMONTHDAY`, … — inklusive korrektem
Verhalten über **Sommer-/Winterzeit-Wechsel** (DST). Beim Auflisten eines Zeitfensters müssen die
konkreten Termine („Occurrences") daraus expandiert werden.

Das selbst zu implementieren ist eine bekannte Fehlerquelle: Wochentags-Bitmasken, Monatsenden,
Intervall-Anker, `UNTIL`-Grenzen (inklusiv/exklusiv) und DST-Sprünge korrekt **und** getestet
hinzubekommen, ist viel Code mit hohem Risiko. Das Tabu der Root-`CLAUDE.md` verlangt für eine neue
Abhängigkeit einen ADR mit „Bestehendes scheitert nachweislich an X".

## Entscheidung

**`python-dateutil`** (Modul `dateutil.rrule`) als RRULE-Engine aufnehmen (+ `types-python-dateutil`
als Dev-Stubs für `mypy --strict`).

**Warum es passt / warum „Bestehendes scheitert":**
- **Bestehendes** (`datetime`, eigene Schleifen) deckt FREQ/INTERVAL/BYDAY/UNTIL/COUNT **nicht**
  korrekt + DST-sicher ab, ohne de-facto eine RRULE-Engine nachzubauen — genau das „X".
- `dateutil` ist die **Referenz-Implementierung** im Python-Ökosystem (Grundlage vieler iCal-Tools),
  rein Python, **keine** nativen/Build-Abhängigkeiten, seit Jahren stabil, breit auditiert.
- Wir nutzen nur `rrulestr(...)` (Parsen + Validieren) und die Occurrence-Iteration in einem
  **gefensterten, gedeckelten** Lauf (max. N Treffer) — kleine, klar umrissene Oberfläche.

## Konsequenzen

- **Positiv:** Korrekte, DST-sichere RRULE-Expansion ohne Eigenbau-Risiko; Validierung ungültiger
  Regeln „for free" (Parse-Fehler → 422). Die reine Expansionsfunktion (`calendar/expand.py`) ist
  **ohne DB unit-testbar**.
- **Negativ / Kosten:** Eine zusätzliche (kleine, reine) Laufzeit-Abhängigkeit + Dev-Stubs. Akzeptabel
  — Standardbibliothek des Ökosystems. Spätere ICS-Im/Export-Slices können dieselbe Engine nutzen.

## Alternativen (verworfen)

- **Eigene RRULE-Schleife** — siehe „X": fehleranfällig (DST, BY*-Regeln, UNTIL-Semantik), viel
  Test-Aufwand für ein gelöstes Problem. Verworfen.
- **`icalendar`/`recurring-ical-events`** — bringt mehr mit (VEVENT-Parsing), als S2 braucht; käme
  ggf. erst beim ICS-Im/Export in Frage. Für reine RRULE-Expansion ist `dateutil` schlanker.
