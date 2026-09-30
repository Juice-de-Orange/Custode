# Modul `scheduling`

**Status:** in Arbeit · **Phase:** 5 · **KONZEPT:** §5.12

## Zweck & Verantwortung
Schlägt konfliktfreie Zeit-Slots für eine Aufgabe vor (KONZEPT §5.12). P5-S8a ist der erste Schritt:
**read-only** Vorschläge aus der Kalender-Belegung, mit maschinenlesbarer Begründung; der Nutzer trägt
einen Slot **opt-in** als Kalender-Event ein. Importiert **nur** `kernel/*` + `calendar.api` +
`weather.api` + `wearables.api` (je nur die `api`-Naht); besitzt
(noch) keine Tabelle.

## Datenobjekte
Keine — `scheduling` ist in S8a zustandslos (read-only). Belegung kommt über die calendar.api-Naht.

## Seams (ADR-0046)
Importiert **nur** `kernel/*` + `calendar.api` + `weather.api` + `wearables.api` (import-linter:
„scheduling uses only calendar/weather/wearables public api" — plus der Kontrakt „wearable consumers
use only its public api", der die Wearables-Internas gezielt sperrt). Nie deren Interna.

`calendar.api.list_busy_intervals(session, viewer_id, frm, to)` liefert die **expandierten**
`(start, end)`-Intervalle der sichtbaren `busy`-Events des Aufrufers — RLS, Layer-Sichtbarkeit
(ADR-0040), RRULE-Expansion und EXDATE sind bereits angewandt. `scheduling` liest nie calendar-Tabellen.

**Abwesenheit (P5-S8b, Synergie S-09):** zusätzlich blockiert
`calendar.api.list_absence_intervals(session, viewer_id, frm, to)` die **eigenen** `absence`-Zeiten des
Aufrufers (`owner_id == viewer_id`, expandiert) — auch wenn das Absence-Event `busy=false` ist. Ein
Mitglied bekommt nie einen Slot während der eigenen Abwesenheit; betroffene Slots tragen zusätzlich den
Begründungs-Code `avoids_absence`. Die Abwesenheit einer Mitbewohnerin blockiert die eigene Planung nicht.

**Wearable-Schonung (P9-S7, Synergie S-14):** `wearables.api.recovery_signal(session,
member_id=viewer_id, today)` liefert **ein Boolean, nie einen Score** — ein roher Gesundheitswert
über einer Modulgrenze *ist* das Gesundheitsdatum. Immer mit `member_id=viewer_id`; die
mitglieds-gescopte RLS liefert für jede andere id nichts (N-2, ADR-0081 §8). Markiert wird **nur
heute** — eine Messung beschreibt die Vergangenheit, nicht nächsten Donnerstag — und erst ab
`LONG_TASK_MINUTES` (90 min), weil S-14 von XL-Tasks spricht. Der Hinweis **entfernt und sortiert
nichts**: die Slot-Menge bleibt identisch, „meiden" ist ein überstimmbarer Hinweis. Ohne
Wearable/Consent/aktuelle Lesung leer → kein Hinweis (graceful).

**Wetter (P5-S8c, Synergie S-15):** `weather.api.get_forecast(session)` liefert (optional) die
Haushalts-Vorhersage; aus den Tageswerten baut der Service `rain_by_date` (Datum → max.
Regenwahrscheinlichkeit). Ein Slot an einem Tag ≥ `RAIN_WARNING_THRESHOLD` (60 %) trägt den Code
`rain_warning`. Ohne Wetter (Flag aus / kein Standort / Null-Provider / Upstream aus) ist die Map leer →
keine Warnung (graceful). Wetter **blockiert nie** — es ist nur ein Hinweis.

## Engine (rein, ADR-0046)
`engine.py::find_free_slots` mischt die Belegung (`merge_intervals`) und carved die freien Lücken
innerhalb der Tagesarbeitszeit `[day_start, day_end]` (vorerst **UTC**) aus; je freier, ausreichend
großer Lücke ein Slot der gewünschten Dauer, hart gedeckelt (`MAX_SLOTS`). Jeder Slot trägt
**Begründungs-Codes** (`no_conflict`, `within_work_hours`, ggf. `avoids_absence`/`rain_warning`/
`low_recovery`); die
**Klartext**-Übersetzung macht das Web
(i18n DE/EN) — kein hartkodierter nutzerseitiger Text im Backend. Rein + ohne Docker testbar.

## Schnittstellen
- **HTTP `/v1/scheduling/slots` (member/admin):** `GET ?from=&to=&duration_min=&day_start=&day_end=&limit=`
  → `list[SlotResponse {start, end, reasons[]}]`. Defaults: Fenster now..now+7 d (max 31 d), Dauer 60 min,
  Arbeitszeit 7–21 UTC, limit 5. 422 bei leerem Fenster / `day_end <= day_start`.
- **Cross-Modul:** importiert **nur** `kernel/*` + `calendar.api`. `scheduling.api` ist leer (kein
  Modul importiert scheduling).
- **Auto-Eintrag:** opt-in — das Web legt aus einem Slot über `POST /v1/calendar/events` ein Event an.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /scheduling/slots` | ✗ (401) | ✗ (403) | ✓ (eigene Belegung) | RLS: nur eigene |

## Tests
- `test_scheduling_engine.py` (rein, P9-S7 erweitert) — `low_recovery` nur ab 90 min, nur am
  markierten Tag, ohne Wearables **byte-identische** Vorschläge, der Hinweis entfernt/sortiert
  nichts, koexistiert mit `rain_warning`.
- `test_scheduling_engine.py` — **reine** Engine-Unit-Tests (Merge, Lücken, Arbeitszeit-Grenzen,
  Mehrtages-Cap, Null-Fälle), ohne Docker.
- `test_scheduling_http.py` — Slots meiden `busy`-Events; `busy=false` blockiert nicht; ungültige
  Arbeitszeiten → 422 (Testcontainers).
- `web/src/scheduling/` — Panel auf der Kalenderseite (Vorschläge + opt-in Eintrag).

## Offene Punkte (spätere Slices)
- **Timezone-aware Arbeitszeiten** + Haushalts-TZ, **Routinen** (capture),
  **Fairness** (economy → `fair_turn`), **Auto-Eintrag** (opt-in automatisch), Slot-Ranking/-Dichte.
  (Abwesenheit: **P5-S8b ✅** · Wetter-Hinweis: **P5-S8c ✅** · Erholungs-Hinweis: **P9-S7 / S-14 ✅**.)
