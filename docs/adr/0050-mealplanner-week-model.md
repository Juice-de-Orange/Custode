# ADR-0050 — Mealplanner: Wochen-Datenmodell + Rezept über recipes.api

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S1
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Phase 6 baut den **Mealplanner** (KONZEPT §5.4) — Wochenplanung des Essens, manuell komfortabel und
später optional vollautomatisch. P6-S1 legt das **manuelle Fundament**, auf dem Automatik-Engine,
Philosophie-Profile und die Einkaufslisten-Regeneration aufsetzen. Zu entscheiden: Wochen-Identität,
Slot-Modell und wie ein Slot ein Rezept referenziert, ohne Modulgrenzen zu verletzen.

## Entscheidung
1. **Zwei Tabellen** (Migration 0042): `meal_plans` (eine Woche je Haushalt, `week_start` = **Montag**
   der ISO-Woche, unique pro Haushalt+Woche) und `meal_slots` (ein Eintrag pro `day_of_week` 0–6 ×
   `slot ∈ {breakfast,lunch,dinner,snack}`, unique pro Plan/Tag/Slot). Beide household-scoped, RLS
   `household_isolation` + FORCE + Negativtest je Tabelle.
2. **Slot = Rezept ODER Freitext** (XOR, Pydantic-validiert): `recipe_id` **oder** `free_text`
   („Reste", „auswärts"), plus `cook_id` („wer kocht") und `note`. Empty/Loading wird durch
   *Abwesenheit* eines Slots dargestellt (keine leeren Zeilen).
3. **Rezept-Referenz ohne DB-FK.** `recipe_id` ist ein nacktes UUID — **kein** Foreign Key auf
   `recipes` (Cross-Modul-Kopplung). Die Titel-Auflösung läuft über `recipes.api.list_recipes`
   (RLS-scoped); ein zwischenzeitlich gelöschtes Rezept „dangelt" einfach auf `recipe_title = None`.
   `mealplanner` importiert nur `kernel/*` + `recipes.api` (neuer import-linter-Contract).
4. **Wochen-Normalisierung serverseitig.** Jeder Endpoint normalisiert ein beliebiges In-Woche-Datum
   auf den Montag (`_monday`), sodass `?week_start=<Mittwoch>` denselben Plan trifft. Plan wird **on
   demand** angelegt (GET einer leeren Woche erzeugt die Plan-Zeile, liefert `slots: []`).
5. **`mealplan.updated`-Event** bei jeder Slot-Änderung (Outbox) → SSE-Entity `"mealplan"`. Das ist
   die **Naht**, an der die spätere **Einkaufslisten-Regeneration** (KONZEPT §5.5, Diff-basiert)
   andockt — bewusst eventgetrieben (kein synchroner Cross-Modul-Aufruf in die Einkaufsliste).

## Konsequenzen
- **Positiv:** saubere Modulgrenze (nur kernel + recipes.api); kein FK-Kopplung; robustes Verhalten bei
  gelöschten Rezepten; idempotente Wochen-Identität; Event-Naht für Phase-3-Einkaufsliste vorbereitet.
- **Abwägung / bewusst später (Folge-Slices):** **Drag&Drop**, **Slots konfigurierbar** (S1 fixiert die
  vier Standard-Slots), **Philosophie-Profile + Constraint-Automatik** (§5.4), **Slot-Regeln**,
  **persönliche Portionsfaktoren**, **`mealplan.cooked`→Rezept-Historie**, und die tatsächliche
  **Einkaufslisten-Regeneration** auf `mealplan.updated`.
- **Grenzen:** `cook_id`/`note` werden gespeichert, aber in der S1-UI nur minimal genutzt; keine
  Nährwert-Aggregation (kommt mit der Automatik + nutrition.api).

## Alternativen
- **FK `meal_slots.recipe_id → recipes.id`:** verworfen — koppelt die Module auf DB-Ebene und würde ein
  Rezept-Löschen am Mealplan scheitern lassen oder kaskadieren; das nackte UUID + api-Auflösung ist
  grenz-sauber und degradiert weich.
- **ISO-Woche als (Jahr, KW) statt `week_start`-Date:** verworfen — Date ist eindeutig, sortierbar und
  vermeidet KW-53/Jahreswechsel-Sonderfälle.
- **Slots als feste Spalten in `meal_plans`** (breakfast/lunch/…): verworfen — konfigurierbare Slots
  (Folge-Slice) brauchen Zeilen, nicht Spalten.
