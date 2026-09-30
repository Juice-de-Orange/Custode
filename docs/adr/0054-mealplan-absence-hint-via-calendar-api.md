# ADR-0054 — Abwesenheits-Hinweis im Wochenplan: read-only via calendar.api (Synergie S-01)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S8
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.4 / Synergie **S-01**: Event-Flags „auswärts / Gäste / Abwesenheit" steuern die
Mealplan-Automatik (Slot überspringen, Portionen +n, Resteverwertung). Der erste, kleinste Baustein
ist ein **read-only Hinweis**: der Wochenplan markiert die Tage, an denen der Betrachter **abwesend**
ist, damit niemand für einen Tag plant/kocht, an dem er weg ist. Die Kalender-Daten dafür liegen im
`calendar`-Modul und werden bereits über `calendar.api` für Scheduling/Fairness gelesen (P5). Zu
entscheiden: Wie kommt der Mealplanner an die Abwesenheiten, und was wird ausgegeben?

## Entscheidung
1. **Read-only über `calendar.api.list_absence_intervals`** (viewer-scoped, EXDATE-honoriert,
   Wiederholungen expandiert) — derselbe einseitige Cross-Modul-Lesepfad wie `scheduling → calendar.api`
   (P5-S8). Der Mealplanner liest **nie** die Kalender-Tabellen direkt.
2. **import-linter:** Der mealplanner-Contract erlaubt nun zusätzlich `calendar.api`, verbietet weiter
   dessen Interna (`calendar.service/models/router/schemas/expand/ics/ics_parse`) und alle anderen
   Module. Name → „mealplanner uses only recipes/shopping/tasks/calendar public api". Einseitig
   (`calendar` kennt den Mealplanner nicht). Weiterhin **14 Contracts**.
3. **Mapping = reine Funktion** `absence.py::absence_weekdays(intervals, *, week_start)` — DB-frei,
   deterministisch, voll unit-getestet: bildet UTC-Intervalle auf die Wochentags-Indizes (0–6) ab, die
   sie innerhalb der Woche überlappen. **Bewusste Vereinfachung:** Tagesgrenzen werden in **UTC**
   verglichen (Abwesenheiten sind i. d. R. ganztägig/mehrtägig → robust); haushalts-zeitzonengenaues
   Mapping ist eine spätere Verfeinerung.
4. **Ausgabe additiv:** `WeekResponse` bekommt `absent_days: list[int]` (Default `[]`). **Nur** der
   `GET /v1/mealplan` füllt es (er hat den Betrachter); die Schreib-/Automatik-Endpunkte (set/suggest/
   copy/…) geben `[]` zurück — das Web holt nach jeder Mutation ohnehin den GET (Query-Invalidierung),
   sodass das Grid den Hinweis bekommt, ohne `calendar` in jeden Endpunkt zu fädeln.

## Konsequenzen
- **Positiv:** keine Migration; reine, erschöpfend testbare Mapping-Funktion; einseitige Modulgrenze
  gewahrt (kein neuer Contract, nur erweitert); additives Schema-Feld (oasdiff non-breaking); nutzt die
  bereits getestete, expandierende `list_absence_intervals`-Naht.
- **Abwägung (E9):** S-01 sieht **Automatik** vor (Slot überspringen, Portionen +n) — S8 liefert nur den
  **Hinweis** (read-only), nicht die Steuerung. Bewusst klein; die Automatik (und „Gäste/auswärts" aus
  `events.flags_json`) baut darauf auf. UTC-Tagesgrenzen sind eine dokumentierte Vereinfachung.
- **Grenzen:** viewer-scoped (nur **meine** Abwesenheit, nicht haushaltsweit) — passend zum „koche ich
  an dem Tag?"-Hinweis; haushaltsweite Sicht + Portionslogik = Folge-Slice.

## Alternativen
- **Haushaltsweite Abwesenheiten** (`list_absences`): verworfen für S8 — liefert Master-Events (Aufrufer
  müsste selbst expandieren) und der Erst-Hinweis ist „bin **ich** weg?"; die viewer-scoped, bereits
  expandierende Naht passt exakt.
- **Eigenes Flag im Mealplanner speichern:** verworfen — Abwesenheit gehört in den `calendar` (eine
  Quelle der Wahrheit); der Mealplanner liest sie nur.
- **`absent_days` in jeder WeekResponse berechnen:** verworfen — würde `calendar` in jeden
  Schreib-Endpunkt fädeln; das Web-Refetch-Muster (GET nach Mutation) deckt es günstiger ab.
