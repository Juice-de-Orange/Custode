# ADR-0040: Kalender — Layer-Sichtbarkeit query-seitig, RLS bleibt tenant-only

- **Status:** beschlossen
- **Datum:** 2026-06-24
- **Betrifft:** `modules/calendar` (neu) · **Bezug:** KONZEPT §5.11, ADR-0034 (PATCH+If-Match)
- **Phase/Slice:** P5-S1

## Kontext

KONZEPT §5.11: der Kalender hat ein **Layer-System**. In S1 zwei Layer: `household` (für alle
Mitglieder sichtbar) und `personal` (nur für den Ersteller sichtbar). Beide leben in **einem** Haushalt
— die Mandanten-RLS (`household_id = app.household_id`) isoliert zwar Haushalte, **nicht** aber
persönliche Termine *innerhalb* eines Haushalts. Wie wird die Privatheit der `personal`-Termine
durchgesetzt?

## Entscheidung

1. **RLS bleibt tenant-only.** `calendar_events` trägt genau die Standard-Policy `household_isolation`
   (USING + WITH CHECK auf `household_id`) wie jede Fachtabelle — Negativtest vorhanden. **Keine**
   per-Owner-RLS-Policy in S1.
2. **Layer-Sichtbarkeit wird query-seitig erzwungen** (`service.py::_visible`): jede Lese-Operation
   filtert `layer = 'household' OR owner_id = <caller>`. `get_event` liefert für einen fremden
   `personal`-Termin **404** (nicht 403 — Existenz wird nicht verraten). Schreiben/Löschen ist
   ohnehin **owner-only** (403 sonst).
3. **Schreibpfad = PATCH + If-Match** (Online-Entität, ADR-0034); `version` = ETag, 412 bei stale,
   428 bei fehlend.

## Konsequenzen

- **Positiv:** Einfach, konsistent mit allen anderen Modulen (eine RLS-Policy-Form), voll testbar
  (HTTP-Test: Co-Mitglied sieht `household`, nicht `personal`). Die Scheduling-Engine (Phase 5) kann
  später über `calendar.api` *alle* `busy`-Termine eines Haushalts lesen (haushaltsweite Belegung),
  ohne dass eine restriktive per-Owner-RLS im Weg steht.
- **Negativ / Kosten:** Die Privatheit hängt an der **Service-Schicht**, nicht an der DB. Jede neue
  Lese-Stelle muss `_visible` verwenden — ein direkter `select(CalendarEvent)` ohne den Filter würde
  fremde persönliche Termine zeigen. Mitigation: alle Reads gehen durch `service.py`; ein künftiger
  direkter DB-Zugriff (z. B. Reporting) müsste den Filter bewusst setzen.

## Alternativen (verworfen)

- **Zweite RLS-Policy `personal_visibility`** (`layer='household' OR owner_id = app.user_id`) — schöbe
  die Privatheit in die DB, kollidiert aber mit dem späteren haushaltsweiten `busy`-Read der
  Scheduling-Engine (die müsste dann unter einer Sonderrolle/Policy laufen). Für S1 unnötig komplex;
  bei wachsendem Bedarf nachrüstbar.
- **Eigene Tabelle je Layer** — dupliziert Schema/Logik ohne Mehrwert. Verworfen.
