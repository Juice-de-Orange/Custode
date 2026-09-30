# ADR-0057 — Nährwert-bewusstes „Woche füllen": closest-to-target Auswahl

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S12
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Das Phase-6-Ziel ist „Auto-Wochenpläne erfüllen Nährwertziele ±10 %". Die Bausteine stehen:
pro-Portion-Makros je Rezept (`recipes.api.recipe_macros`, P6-S10), die ±10%-Bewertung
(`evaluate_target`, P6-S11) und das verteilende „Woche würfeln" (`suggest_many`, P6-S5). Offen: die
**Auto-Auswahl**, die leere Slots so füllt, dass das kcal-Ziel getroffen wird.

## Entscheidung
1. **Auswahl = reine Funktion** `suggest.py::pick_for_target(candidates, *, target_kcal, count,
   exclude_ids)` — Kandidaten sind `(id, kcal)`; deterministisch nach **absolutem Abstand** zum Ziel
   sortiert (Tiebreak `id`), `exclude_ids` raus, die `count` nächsten zurück. **Invariante** (Property-
   Test, Hypothesis): kein verworfenes geeignetes Rezept ist strikt näher am Ziel als ein gewähltes.
   Best-effort (weniger als `count`, wenn der Pool kleiner ist).
2. **Integriert in `POST /v1/mealplan/suggest-week`** als optionaler `target_kcal`-Query-Parameter:
   ohne ihn bleibt es least-recently-cooked (ADR-0052), mit ihm wird closest-to-target gefüllt. Makros
   je Kandidat über `recipes.api.recipe_macros` (kein `nutrition`-Import; recipes.api seit P6-S1 erlaubt).
   Geschrieben über den bestehenden `set_slot`-Pfad (ein Schreibpfad), non-destruktiv (nur leere Slots),
   **kein 422** (leerer Pool füllt nichts). Keine Migration, kein neuer import-linter-Contract.
3. **„Closest per slot" statt Kombinatorik-Optimierung** in S12: jeder Slot bekommt ein Rezept nahe am
   **Pro-Portion-Ziel**; es wird **nicht** eine Kombination optimiert, die eine Tages-/Wochensumme trifft.
   Das ist die bewusst einfache, deterministische erste Stufe — sie trifft das Ziel, wenn der Pool
   Rezepte nahe am Ziel enthält (genau der ±10%-Fall der Done-Kriterien).

## Konsequenzen
- **Positiv:** liefert die Kern-Automatik des Phase-6-Ziels mit einer reinen, property-getesteten
  Funktion; nutzt die bestehenden Makro-/Schreib-Nähte; Modulgrenzen gewahrt (kein `nutrition`-Import);
  ein Endpunkt, zwei Strategien (kein API-Wildwuchs). `evaluate_target` (S11) macht das Ergebnis
  überprüfbar (das Web zeigt „im Ziel ±10 %" nach dem Füllen).
- **Abwägung (E9):** „je Slot das nächste Rezept" ist **keine** echte Kombinations-Optimierung. Für ein
  reines **Pro-Portion-kcal-Ziel** ist es optimal (jeder Slot minimiert |kcal−Ziel|); für mehrdimensionale
  Ziele (Protein/Allergien/Abwechslung gleichzeitig) ist es eine Heuristik. Mehrkriterielle Optimierung +
  Philosophie-Profile sind Folge-Slices.
- **Grenzen:** N `recipe_macros`-Aufrufe (je Kandidat) — für Haushalts-Rezeptmengen vernachlässigbar,
  eine Batch-Variante ist später möglich. Keine Wiederholungs-Sperre im Ziel-Modus (Priorität ist das
  Ziel); Variety + Lockout zusätzlich zu gewichten ist ein Folge-Slice.

## Alternativen
- **Kombinatorische Optimierung** (Teilmengen, die die Wochensumme treffen): verworfen für S12 — komplex
  (Rucksack-artig) und für ein Pro-Portion-Ziel unnötig; kommt mit mehrkriteriellen Profilen.
- **Zufalls-Sampling gewichtet nach Nähe:** verworfen — nicht reproduzierbar testbar; die deterministische
  closest-Auswahl ist die klare erste Stufe (Streuung kann später bewusst dazukommen).
- **Eigener Endpunkt `fill-for-target`:** verworfen — dieselbe Operation (leere Slots füllen) mit anderer
  Auswahl; ein optionaler Parameter an `suggest-week` hält die API klein.
