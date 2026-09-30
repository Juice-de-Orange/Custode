# ADR-0055 — Vorbereitungs-Task am Vortag: Lead-Time-Heuristik + tasks.api (Synergie S-02)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S9
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.2/§5.4 / Synergie **S-02**: Rezeptschritte mit Vorlauf (auftauen, marinieren, Teig gehen)
sollen beim Einplanen einen **Vorbereitungs-Task am Vortag** erzeugen („Hähnchen auftauen"). Rezepte
tragen heute **kein** strukturiertes Vorlauf-Feld — nur `steps_md` (Markdown) + `tags`. Zu entscheiden:
Wie wird der Vorlauf erkannt, und wie entsteht die Aufgabe?

## Entscheidung
1. **Erkennung = reine Heuristik** `prep.py::needs_prep(steps_md, tags) -> str | None` — DB-frei,
   deterministisch, voll unit-getestet: scannt `steps_md` + `tags` case-insensitiv nach Vorlauf-Cues
   (DE+EN: auftauen/marinieren/einweichen/über Nacht/gehen lassen/quellen · thaw/marinate/soak/
   overnight/let rise/…) und gibt den **ersten** Treffer (Prioritäts-Reihenfolge) als kurzen Hinweis
   zurück, sonst `None`. Der Hinweis erscheint im Task-Titel, damit der Nutzer das **Warum** sieht.
2. **Aktion + Aufgabe wie der Koch-Task (S-03/ADR-0053):** `POST /v1/mealplan/slot/prep-task` legt
   bei Treffer „Vorbereiten: <Gericht> (<Hinweis>)" über `tasks.api.create_personal_task` an (points 0,
   einseitig), zugewiesen an `cook_id` oder den Auslöser. **422**, wenn der Slot kein Rezept hat
   (Freitext/leer) **oder** nichts vorzubereiten ist. Rezeptdaten kommen über `recipes.api.get_recipe`
   (steps/tags) — **kein** Direktlesen. **Kein** neuer import-linter-Contract (recipes.api + tasks.api
   sind seit P6-S7 erlaubt), **keine** Migration.
3. **Fälligkeit „am Vortag" als Hinweis, nicht als Termin:** der Task ist ein persönlicher Task ohne
   `due_at` (tasks vergibt kein Datum über `create_personal_task`); „am Vortag" steckt in der
   Bedeutung. Echte Terminierung (due_at = Slot-Tag − 1) kommt mit der Task-Scheduling-Integration.

## Konsequenzen
- **Positiv:** liefert die S-02-Essenz (Vorlauf-Bewusstsein) mit einer reinen, erschöpfend testbaren
  Funktion; nutzt die bestehende, getestete `create_personal_task`-Naht; keine Migration/kein neuer
  Contract; spiegelt den Koch-Task (konsistente UX: 🧊-Button je Rezept-Slot).
- **Abwägung (E9):** KONZEPT denkt an **strukturierte** Vorlauf-Schritte; S9 nutzt eine **Heuristik**
  über Freitext-Schritte/Tags (bewusst, da Rezepte kein Vorlauf-Feld haben). Falsch-negativ möglich
  (unübliche Formulierung) — dann legt der Nutzer den Task manuell an; Falsch-positiv unkritisch (eine
  übersehbare Aufgabe). Strukturierte Schritte + echte Terminierung sind Folge-Slices.
- **Grenzen:** keine `due_at`-Terminierung in S9; explizite Aktion (kein Auto-Erzeugen beim Einplanen)
  — Auto-Erzeugung beim `set_slot` ist ein bewusster späterer Schritt (vermeidet Task-Spam, bis die
  Terminierung/Dedup steht).

## Alternativen
- **Auto-Erzeugen beim Einplanen** (im `set_slot`): verworfen für S9 — ohne Dedup/`due_at` entsteht
  Task-Spam bei jeder Slot-Änderung; erst mit Terminierung + Idempotenz sinnvoll.
- **Strukturiertes Vorlauf-Feld am Rezept** (Migration + UI): verschoben — größerer Eingriff ins
  `recipes`-Modell; die Heuristik liefert sofort Wert auf Bestandsdaten.
- **LLM-Erkennung des Vorlaufs:** verworfen (Phase 7) — die deterministische Heuristik ist testbar,
  offline und ausreichend für die häufigen Fälle.
