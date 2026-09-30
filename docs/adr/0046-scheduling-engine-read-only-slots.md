# ADR-0046 — Scheduling-Engine: read-only Slot-Vorschläge über die calendar.api-Naht

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S8a
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.12 will eine **Scheduling-Engine** (Arbeitszeiten · Routinen · Wetter · Fairness →
Vorschläge mit **Klartext-Begründung**, opt-in Auto-Eintrag). Das ist groß und mehrstufig. Der erste
Slice braucht eine klare Architektur, ohne sich zu übernehmen — und muss die Modulgrenzen wahren
(`scheduling` darf calendar-Tabellen nicht direkt lesen).

## Entscheidung
1. **Eigenes Modul `scheduling`, das nur `kernel/*` + `calendar.api` importiert.** Neue import-linter-
   Contract „scheduling uses only calendar's public api" (verbietet calendar-Interna + alle anderen
   Module). `scheduling` ist ein **einseitiger Konsument** — kein Modul importiert `scheduling`.
2. **Belegung über eine neue calendar.api-Naht.** `calendar.api.list_busy_intervals(session,
   viewer_id, frm, to)` liefert die **expandierten** `(start, end)`-Intervalle der sichtbaren
   `busy`-Events des Aufrufers (RLS + Layer-Sichtbarkeit + RRULE-Expansion + EXDATE schon angewandt).
   So liest `scheduling` nie die Tabelle, und die Sichtbarkeitsregeln (ADR-0040) gelten automatisch.
3. **Reine Engine.** `scheduling/engine.py::find_free_slots` ist DB-/I/O-frei und ohne Docker testbar
   (Kalender-Muster): merge der Belegung → freie Lücken in der Tagesarbeitszeit → konfliktfreie Slots
   der gewünschten Dauer, hart gedeckelt (`MAX_SLOTS`). Jeder Slot trägt **maschinenlesbare**
   Begründungs-Codes (`no_conflict`, `within_work_hours`); die **Klartext**-Übersetzung macht das Web
   (i18n DE/EN) — kein hartkodierter nutzerseitiger Text im Backend.
4. **Read-only + opt-in Eintrag.** `GET /v1/scheduling/slots` schlägt nur vor; der Nutzer trägt einen
   Slot **explizit** als Kalender-Event ein (Web ruft den bestehenden `POST /v1/calendar/events`).
   Kein automatischer Schreibpfad, keine eigene Tabelle in diesem Slice.

## Konsequenzen
- **Positiv:** saubere Modulgrenze (nur kernel + calendar.api); Sichtbarkeit/RLS automatisch korrekt;
  reine Engine → schnelle, gründliche Unit-Tests ohne Container; i18n-saubere Begründungen; keine
  Migration, kein neuer Schreibpfad → minimales Risiko; klar erweiterbar.
- **Abwägung / bewusst später:** **Arbeitszeiten** sind vorerst feste UTC-Stunden (Query-Parameter,
  Default 7–21) — **timezone-aware** Arbeitszeiten + Haushalts-TZ kommen mit der Standort-/TZ-Arbeit.
  **Routinen** (capture P4-S9c), **Wetter-Signal** (`weather.api`-Naht), **Fairness** (economy) und
  **Auto-Eintrag** sind eigene Folge-Slices — die Begründungs-Codes sind genau dafür der Erweiterungs-
  punkt (weitere Codes: `weather_ok`, `avoids_absence`, `fair_turn`).
- **Grenzen:** ein Slot je freier Lücke (an deren Beginn) — keine Slot-Dichte/Ranking in S8a.

## Alternativen
- **scheduling liest calendar-Tabellen direkt:** verworfen — Modulgrenz-Bruch; Sichtbarkeits-/RLS-Logik
  müsste dupliziert werden.
- **Klartext-Begründung serverseitig formulieren:** verworfen — verletzt die i18n-Regel; Codes +
  Web-Übersetzung sind sauberer und mehrsprachig.
- **Eigene `schedule_suggestions`-Tabelle / Auto-Eintrag jetzt:** verworfen — unnötiger Schreibpfad;
  read-only + opt-in ist der risikoärmste erste Schritt.
