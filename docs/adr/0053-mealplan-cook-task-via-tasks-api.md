# ADR-0053 — Koch-Task aus einem Mealplan-Slot: synchron via tasks.api (Synergie S-03)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S7
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.4 / Synergie **S-03** („Wer kocht heute"): ein Mealplan-Slot ist mit dem Kochen als
Aufgabe verknüpfbar. Der erste, kleine Baustein ist eine **explizite Aktion**: aus einem geplanten
Slot eine persönliche **Koch-Aufgabe** erzeugen („Kochen: <Gericht>"), zugewiesen an den im Slot
hinterlegten Koch (`cook_id`) — oder an den Auslöser, falls keiner gesetzt ist. Die volle S-03
(Rotation, Fairness, **Punkte fürs Kochen**, eigener Kalender-Layer, Template-Verknüpfung) baut darauf
auf. Zu entscheiden: Wer legt die Aufgabe an und über welchen Pfad?

## Entscheidung
1. **Synchron via `tasks.api.create_personal_task`** in derselben Transaktion wie die Mealplanner-
   Aktion — derselbe sanktionierte, einseitige Cross-Modul-Pfad wie `mealplanner → recipes.api`
   (ADR-0050/0051) und `→ shopping.api` (ADR-0050) sowie `capture → tasks.api` (ADR-0038). `tasks`
   bietet bereits die **primitiv-argumentige** Naht `create_personal_task(household_id, title,
   assigned_to)` (points 0, KONZEPT §5.6/5.9) — Mealplanner muss **keine** tasks-Schemas importieren.
2. **import-linter:** Der bestehende mealplanner-Contract erlaubt nun zusätzlich `tasks.api`, verbietet
   weiterhin dessen Interna (`tasks.service/models/router/schemas`) und alle anderen Module. Name →
   „mealplanner uses only recipes/shopping/tasks public api". Die Abhängigkeit bleibt **einseitig**
   (`tasks` kennt den Mealplanner nicht). Weiterhin **14 Contracts** (nur Inhalt erweitert).
3. **Aktion:** `POST /v1/mealplan/slot/cook-task?week_start=&day_of_week=&slot=` (member/admin, CSRF)
   legt die Koch-Aufgabe an und gibt `{title, assigned_to}` zurück. **422**, wenn der Slot leer ist
   (kein Rezept **und** kein Freitext → kein Gericht zum Kochen). Titel = Rezepttitel (über
   `recipes.api`) **oder** Freitext; Zuweisung = `cook_id` **oder** der auslösende Nutzer.
4. **Keine neue Tabelle, kein Slot↔Task-Link in S7.** Die Aktion ist **explizit** (Button) — sie
   speichert keine Verknüpfung und ist daher bewusst **nicht** idempotent (zweimal klicken = zwei
   Aufgaben, wie zweimaliges manuelles Anlegen). Eine persistente Verknüpfung (für Rotation/Punkte/
   Auto-Sync bei Slot-Änderung) ist Teil der späteren, vollen S-03.

## Konsequenzen
- **Positiv:** atomar + sofort sichtbar; nutzt eine bereits existierende, getestete Naht
  (`create_personal_task`); einseitige Modulgrenze gewahrt; keine Migration; das `task.created`-Event
  (Outbox → SSE „tasks") sorgt für Live-Update der Aufgabenlisten.
- **Abwägung (E9):** KONZEPT-S-03 sieht eine **Verknüpfung** Slot↔Task-Template mit Punkten/Rotation
  vor — S7 liefert nur die **manuelle Erzeugung** ohne persistenten Link und ohne Punkte (persönliche
  Aufgabe, points 0). Bewusst klein gehalten und dokumentiert; die Punkte-/Rotations-Mechanik kommt im
  Folge-Slice (braucht den Link + economy-Einbindung).
- **Grenzen:** keine Dedup/kein Auto-Update bei Slot-Änderung in S7 (siehe oben); Kinder-Accounts wie
  bei allen Mealplan-Writes ausgenommen (member/admin).

## Alternativen
- **Rein eventgetrieben** (`mealplan.*`-Handler legt die Aufgabe an): verworfen für die *Aktion* —
  nicht atomar zur expliziten Nutzeraktion, verzögert sichtbar, zweiter Worker-Pfad; das Event bleibt
  für andere Konsumenten erhalten.
- **Task-Template „Kochen" + Instanz-Generierung** (volle S-03): verschoben — braucht den persistenten
  Slot↔Template-Link, Rotation und economy-Punkte; zu groß für diesen Slice.
- **Eigene Koch-Task-Tabelle im Mealplanner:** verworfen — Aufgaben gehören in `tasks` (eine Quelle der
  Wahrheit für Erledigung/Historie/Fairness); der Mealplanner liest/schreibt sie nur über `tasks.api`.
