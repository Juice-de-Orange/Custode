# ADR-0036: Wert-Verfall überfälliger Aufgaben — Defaults & Anwendung bei Erledigung

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `modules/tasks`, `modules/economy` · **Bezug:** KONZEPT §5.9 (Entscheidung 17.1), ADR-0035
- **Phase/Slice:** P4-S4

## Kontext

KONZEPT §5.9 (17.1) ersetzt Strafen durch **sanften Wert-Verfall**: Niemandem werden Punkte vom Saldo
abgezogen; stattdessen schmilzt der **Punktwert** einer überfälligen Aufgabe (Default −10 %/Tag,
Untergrenze 50 %, pro Haushalt einstellbar/abschaltbar). Mit P4-S2/S3 steht das Ledger; die Gutschrift
ist synchron bei der Erledigung (ADR-0035). Offen: **wann/wie** der Verfall wirkt und **wie konfiguriert**.

## Entscheidung

1. **Anwendung bei der Erledigung.** `tasks.complete_instance` berechnet den **effektiven** Punktwert
   `effective_points(base, due_at, now)` (reine Funktion, `tasks/decay.py`) und bucht **diesen** ins
   Ledger (`economy.api.credit_task_completion`). Der Verfall ist damit ein Eigenschaft des
   Gutschrift-Betrags, nicht des Saldos — die Nicht-Negativ-Regel bleibt unberührt.
2. **Tagesschritte, nicht stetig.** Verfall pro **vollem** Tag über der Fälligkeit
   (`(now − due_at).days`): < 24 h überfällig = noch voll. Einfach erklärbar, ruckelfrei genug.
   `multiplier = max(0.5, 1 − 0.10 × Tage)`, `round(base × multiplier)`.
3. **`awarded_points`-Spalte** (Migration 0026, additiv-nullable) hält den tatsächlich gutgeschriebenen
   (ggf. verfallenen) Betrag je Instanz fest — für Anzeige („du hast X verdient") und Audit gegen das
   Ledger. NULL = noch nicht erledigt.
4. **P4-S4 nutzt feste Defaults** (−10 %/Tag, Floor 50 %). Die **per-Haushalt-Konfiguration**
   (`households.settings_json`, abschaltbar) folgt als kleiner Folge-Slice; die Konstanten sind dann die
   Defaults. So bleibt S4 ohne neue Cross-Modul-Abhängigkeit (`tasks` müsste sonst die Haushalts-
   Settings über `accounts.api` lesen).
5. **Web-Spiegel** (`web/src/tasks/decay.ts`) zeigt nur eine **Vorschau** des aktuellen Werts einer
   offenen überfälligen Aufgabe; autoritativ ist stets die Server-Berechnung bei der Erledigung.

## Konsequenzen

- **Positiv:** Verfall ist auditierbar (`awarded_points` + Ledger), erklärbar (Tagesschritte), und greift
  ohne Strafmechanik. Property-Tests sichern die Invarianten (Wert ∈ [50 %·base, base], monoton fallend,
  voll ohne Frist/vor Fälligkeit).
- **Negativ / Kosten:** Backend- und Web-Konstanten müssen synchron bleiben (kommentiert). Bis zum
  Config-Folge-Slice ist der Verfall nicht pro Haushalt abschaltbar (bewusst, YAGNI-Schnitt).

## Alternativen (verworfen)

- **Stetiger (stündlicher) Verfall** — minutiös „korrekt", aber schwer erklärbar und unruhig in der UI.
- **Verfall als nächtlicher Cron, der `points` umschreibt** — verletzt „Snapshot/append-only"-Denken
  und macht den Wert zeitabhängig-mutierend; die Berechnung bei der Erledigung ist einfacher und exakt.
- **Per-Haushalt-Config sofort** — zwänge `tasks → accounts.api` (Settings-Lesepfad) in denselben Slice;
  als eigener kleiner Slice sauberer trennbar.
