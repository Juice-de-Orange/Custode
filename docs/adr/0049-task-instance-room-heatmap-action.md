# ADR-0049 — Heatmap als Aktionsfläche: direktes `task_instances.room_id`

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S11 (Synergie S-13)
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Die Raum-Heatmap (P4-S6) zeigt je Raum die Frische (grün/gelb/rot) aus der letzten Erledigung
zugehöriger Tasks. Synergie **S-13** will die Heatmap zur **Aktionsfläche** machen: aus einem roten
Raum heraus direkt eine Aufgabe anlegen. Bisher gehört ein Task einem Raum **nur** über sein Template
(`task_templates.room_id`); eine **ad-hoc** Aufgabe (ohne Template) kann keinem Raum zugeordnet werden —
und würde die Heatmap des Raums nie aktualisieren.

## Entscheidung
1. **Optionales `task_instances.room_id`** (Migration 0041, nullable, indiziert, additiv). So kann eine
   ad-hoc Instanz direkt einem Raum gehören. `create_instance` übernimmt `room_id` aus dem Request.
2. **Effektiver Raum = `COALESCE(instance.room_id, template.room_id)`.** `room_last_done` zählt eine
   Erledigung für den effektiven Raum (Sub-Query: erledigte Instanzen LEFT JOIN Template, Gruppierung
   per effektivem Raum). Eine direkt zugeordnete ad-hoc-Erledigung lässt den Raum also grün werden — die
   Heatmap-Aktion ist damit **wirksam**, nicht nur kosmetisch.
3. **Web:** die Heatmap-Karten bekommen „+ Aufgabe" → Inline-Titel → `POST /v1/tasks/instances`
   `{title, room_id}`. Eine Erledigung invalidiert zusätzlich die Heatmap-Query (Farbe aktualisiert
   prompt). Modulgrenzen unverändert (`tasks` bleibt in sich; kein Cross-Modul-Import).

## Konsequenzen
- **Positiv:** ad-hoc Aufgaben sind raum-zuordenbar; Heatmap spiegelt sie korrekt; additive Migration
  (Bestand = `NULL`, exakt altes Verhalten); kleine, klar getestete Service-Änderung.
- **Abwägung:** zwei Wege zur Raumzugehörigkeit (Template **oder** direkt) — bewusst via `COALESCE`
  vereinheitlicht; der direkte Wert hat Vorrang, falls beides gesetzt ist (eine ad-hoc-Override-Semantik).
- **Grenzen:** Anlegen ändert die Heatmap nicht (nur **Erledigen** zählt zur Frische) — gewollt; die
  Aktion adressiert einen roten Raum, grün wird er erst nach Erledigung.

## Alternativen
- **Nur über ein Template anlegen:** verworfen — erzwingt für jede schnelle Aufgabe ein Template; die
  Heatmap-Aktion soll ein 1-Tap-Eintrag sein.
- **Heatmap rein kosmetisch verlinken (zu /tasks):** verworfen — ohne Raum-Zuordnung bliebe die neue
  Aufgabe für die Frische des Raums unsichtbar; die Synergie wäre wirkungslos.
