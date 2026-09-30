# ADR-0051 — „Zuletzt gekocht"-Historie: synchron via recipes.api + `mealplan.cooked`-Event

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S3
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.2/§5.4: Rezepte tragen eine **„zuletzt gekocht"-Historie**, die **vom Mealplanner** gespeist
wird (Event `mealplan.cooked`) — Fundament für die spätere Automatik-Wiederholungs-Sperre („schlage ein
Rezept nicht innerhalb von X Tagen erneut vor"). Zu entscheiden: Wer schreibt die Historie in `recipes`,
und über welchen Pfad (synchron vs. rein eventgetrieben)?

## Entscheidung
1. **Datenfelder in `recipes`** (Migration 0043, additiv): `last_cooked_at` (timestamptz) +
   `cooked_count` (int). In `RecipeResponse`/`RecipeSummary` ausgegeben.
2. **Synchron via `recipes.api.mark_cooked`** in derselben Transaktion wie die Mealplanner-Aktion —
   **nicht** rein über einen Event-Handler. Begründung wie ADR-0035 (Ledger-Gutschrift): `mealplanner`
   importiert ohnehin `recipes.api` (einseitig, erlaubt); ein synchroner Aufruf ist **atomar**,
   **sofort sichtbar** und vermeidet einen zweiten Worker-Pfad. Die Abhängigkeit bleibt einseitig
   (`mealplanner → recipes.api`; `recipes` weiß nichts vom Mealplanner).
3. **`mealplan.cooked`-Event wird trotzdem emittiert** (Outbox) und im SSE-Registry auf die Entity
   **`recipes`** gemappt — so aktualisiert die Rezeptliste live (auf anderen Geräten) und das Event
   bleibt die dokumentierte Naht für spätere Konsumenten (Analytik/Automatik), genau wie KONZEPT es
   vorsieht. Die *Datenwirkung* ist aber synchron, nicht vom Handler abhängig.
4. **Aktion:** `POST /v1/mealplan/slot/cooked?week_start=&day_of_week=&slot=` markiert das Rezept des
   Slots als gekocht (member/admin, CSRF). 422 wenn der Slot leer/Freitext ist (kein Rezept).

## Konsequenzen
- **Positiv:** atomar + sofort; keine Race zwischen „gekocht" und „Historie sichtbar"; einseitige
  Modulgrenze gewahrt (kein neuer import-linter-Contract — `mealplanner → recipes.api` war schon
  erlaubt); Event-Naht bleibt für Phase-spätere Konsumenten erhalten; additive Migration.
- **Abwägung / bewusste Abweichung (E9):** KONZEPT formuliert die Historie „vom Event" — wir buchen sie
  **synchron** und nutzen das Event nur für SSE/zukünftige Konsumenten (wie ADR-0035 beim Ledger). Klar
  dokumentiert; das Verhalten ist identisch (Event wird publiziert), nur die Datenwirkung ist nicht
  handler-abhängig.
- **Grenzen:** `cooked_count` wird erhöht, aber in der S3-UI nur `last_cooked_at` angezeigt; die
  Automatik-Wiederholungs-Sperre selbst ist ein Folge-Slice.

## Alternativen
- **Rein eventgetrieben** (Composition-Root-Handler auf `mealplan.cooked` → `recipes.mark_cooked`):
  verworfen für die *Datenwirkung* — nicht atomar, verzögert sichtbar, zweiter Worker-Pfad; das Event
  bleibt aber für SSE/Spätere erhalten.
- **Cook-Status auf dem Slot speichern statt auf dem Rezept:** verworfen — die Historie gehört zum
  **Rezept** (mehrfaches Kochen über Wochen), nicht zur einzelnen Slot-Zelle.
