# CLAUDE.md — Modul `scheduling`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Schlägt **konfliktfreie Zeit-Slots** für eine Aufgabe vor (KONZEPT §5.12). P5-S8a: read-only
Vorschläge auf Basis der Kalender-Belegung; der Nutzer trägt einen Slot **opt-in** als Event ein.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + `calendar.api` + `weather.api` + `wearables.api` (import-linter:
  „scheduling uses only calendar/weather/wearables public api"). **Nie** deren Interna oder ein
  anderes Modul. Kein Modul importiert `scheduling` (einseitig → kein Zyklus). Eigene `api.py`
  ist leer.
- **Keine eigene Tabelle** in S8a. **Kein** automatischer Schreibpfad — Vorschläge sind read-only;
  der Eintrag läuft explizit über `POST /v1/calendar/events` (Web).

## Belegung (calendar.api-Naht, ADR-0046)
- `calendar.api.list_busy_intervals(session, viewer_id, frm, to)` liefert die **expandierten**
  `(start, end)` der sichtbaren `busy`-Events (RLS + Layer-Sichtbarkeit + RRULE + EXDATE schon drin).
  **Nie** die Belegung selbst aus Tabellen zusammenbauen — immer über die Naht.
- `calendar.api.list_absence_intervals(...)` (P5-S8b) blockiert zusätzlich die **eigenen**
  `absence`-Zeiten des Aufrufers (auch `busy=false`) → Code `avoids_absence`. Fremde Abwesenheit
  blockiert nicht.
- `weather.api.get_forecast(session)` (P5-S8c) → `rain_by_date`; Tag ≥ 60 % Regen → Code
  `rain_warning`. Wetter **blockiert nie** (nur Hinweis); ohne Wetter leer → keine Warnung (graceful).
- `wearables.api.recovery_signal(session, member_id=viewer_id, today)` (P9-S7, Synergie S-14) →
  `low_recovery_dates`; ab 90 min Dauer (`LONG_TASK_MINUTES`) → Code `low_recovery`. **Immer mit
  `member_id=viewer_id`** — das Signal formt nur die Vorschläge dieses Mitglieds, und die
  mitglieds-gescopte RLS liefert für jede andere id nichts. **Nur heute** wird markiert: eine
  Messung beschreibt die Vergangenheit, nicht nächsten Donnerstag. Ohne Wearable/Consent/aktuelle
  Lesung leer → kein Hinweis (graceful).

## Engine (rein)
- `engine.py::find_free_slots` ist **rein** (ohne DB/I/O, ohne Docker testbar). Gedeckelt
  (`MAX_SLOTS`). Gibt Begründungs-**Codes** zurück (`no_conflict`, `within_work_hours`) — die
  **Klartext**-Übersetzung macht das Web (i18n). **Nie** nutzerseitigen Text serverseitig hartkodieren.
- Arbeitszeiten sind vorerst **feste UTC-Stunden** (Query-Param). Timezone-aware Arbeitszeiten,
  Routinen, Wetter-Signal, Fairness, Auto-Eintrag = **spätere** Slices (neue Begründungs-Codes).

## Schnittstellen (HTTP, `/v1/scheduling`)
- `GET /v1/scheduling/slots?from=&to=&duration_min=&day_start=&day_end=&limit=` (member/admin)
  → `list[SlotResponse {start, end, reasons[]}]`. 422 bei `day_end <= day_start` / leerem Fenster.

## No-Gos
- **Kein** Cross-Modul-Import außer `calendar.api` / `weather.api` / `wearables.api`.
  **Kein** Tabellen-Lesen.
- **Nie** einen Slot wegen `low_recovery` weglassen oder umsortieren — nur markieren. Verstecken
  würde vom Basis-Pfad abweichen und für den Menschen entscheiden.
- **Nie** ein Wearable-Signal für ein anderes Mitglied als den Aufrufer abfragen (N-2).
- **Kein** automatischer Kalender-Schreibpfad (nur Vorschlag; Eintrag opt-in).
- **Keine** hartkodierte nutzerseitige Begründung (Codes + Web-i18n).
