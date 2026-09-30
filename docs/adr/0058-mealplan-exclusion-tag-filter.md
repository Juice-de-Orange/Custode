# ADR-0058 — Allergie-/Ausschluss-Filter beim Auto-Füllen: Tag-basiert

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S13
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Das Phase-6-Ziel verlangt Auto-Wochenpläne „**ohne Allergie-Verstöße**". Die Auto-Füll-Auswahl (P6-S12)
braucht daher einen **Ausschluss-Filter**: Rezepte mit unerwünschten Eigenschaften (Allergene, Diät-
Ausschlüsse) dürfen nicht vorgeschlagen werden. Rezepte tragen heute kuratierte `tags: list[str]`;
kanonische Allergen-Daten aus Zutaten gibt es noch nicht (`recipe_ingredients.ingredient_id` ist
gemappt, ein Allergen-Korpus fehlt).

## Entscheidung
1. **Filter = reine Funktion** `filters.py::has_excluded_tag(recipe_tags, excluded)` (+ `normalize_tags`)
   — case-insensitiv, DB-frei, deterministisch, unit-getestet. Ein Rezept fällt raus, sobald **ein** Tag
   in der Ausschlussmenge liegt. Leere Ausschlussmenge schließt nichts aus.
2. **Tag als Signal (nicht Zutaten-Parsing) in S13.** Der Ausschluss greift auf die **kuratierten
   Rezept-Tags** (z. B. „nuss", „laktose", „vegetarisch"-Gegenteil). Ingredient-`raw_text` wird **nicht**
   geparst — das wäre unzuverlässig ohne kanonischen Allergen-Korpus (ein Folge-Slice kann Allergene aus
   `ingredient_id` ableiten und mit den Tags vereinen).
3. **Integriert in `suggest-week`** als wiederholbarer `exclude_tag`-Query-Parameter: die Rezeptliste wird
   **vor** beiden Auswahlstrategien (least-recently-cooked / closest-to-target) gefiltert. Kombinierbar mit
   `target_kcal` → genau der „±10 % **ohne** Allergie-Verstöße"-Fall des Done-Kriteriums. Keine Migration,
   kein neuer import-linter-Contract (rein lokale Logik + `recipes.api`).

## Konsequenzen
- **Positiv:** schließt die „ohne Allergie-Verstöße"-Lücke des Phase-6-Ziels mit einer reinen, testbaren
  Funktion; greift für **beide** Auto-Füll-Strategien; nutzt vorhandene Rezept-Tags (kein neues
  Datenmodell); kombinierbar mit dem kcal-Ziel.
- **Abwägung (E9):** **Tag-basiert** statt zutaten-/allergen-genau — ein Rezept ohne den Tag „nuss"
  rutscht durch, auch wenn es Nüsse enthält (Datenpflege-Verantwortung liegt beim kuratierten Tag).
  Bewusst, dokumentiert; der kanonische Allergen-Abgleich (aus `ingredient_id`) ist ein Folge-Slice und
  kann denselben Filter speisen.
- **Grenzen:** keine persistente Profil-/Allergen-Liste je Person/Haushalt in S13 (Ausschluss ist ein
  Request-Parameter, wie `target_kcal`); persistente Philosophie-/Allergie-Profile (settings_json) sind
  ein Folge-Slice.

## Alternativen
- **Zutaten-`raw_text`-Scan nach Allergen-Wörtern:** verworfen für S13 — ohne kanonischen Korpus
  fehleranfällig (Falsch-negativ bei Synonymen/Schreibweisen); der kuratierte Tag ist das verlässlichere
  Erst-Signal.
- **Allergene aus `ingredient_id` + Nutrition-Korpus:** der richtige Weg für „genau", aber er braucht
  einen Allergen-Datensatz (neue Referenzdaten) — eigener Slice; dieser Filter ist die Naht, die ihn
  später konsumiert.
- **Hartes 422 bei „kein Rezept übrig":** verworfen — best-effort (leer = nichts füllen) ist konsistent
  mit `suggest-week`; das Web zeigt das leere Ergebnis, der Nutzer lockert den Ausschluss.
