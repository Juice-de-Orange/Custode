# ADR-0037: Marketplace — Escrow über das Ledger, einseitige Modulgrenzen, expliziter Settle

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `modules/marketplace` (neu), `modules/tasks`, `modules/economy` · **Bezug:** KONZEPT §5.10/§5.9, ADR-0035 (Ledger), ADR-0034 (tasks)
- **Phase/Slice:** P4-S8a

## Kontext

KONZEPT §5.10: ein Mitglied verkauft eine ihm zugewiesene, offene Task-Instanz zu einem Preis; der
Preis wird sofort als **Escrow** reserviert (verhindert negative Salden + Doppel-Listing), die Task
wechselt beim Annehmen den Besitzer, und der Escrow wird **erst bei Erledigung** an den Käufer
ausgezahlt (Käufer behält zusätzlich die Basis-Punkte, Audit A-04). Done-Kriterium (Phase 4):
„Saldensumme inkl. Escrow konstant & nie negativ; Marketplace-Statusmaschine vollständig".

Das wirft zwei Architektur-Fragen auf:
1. **Wo lebt der Escrow?** (Tabu §5.9: keine Saldo-Felder.)
2. **Wie reagieren die Module aufeinander**, ohne einen Import-**Zyklus** zu bauen?
   marketplace braucht tasks (Instanz prüfen/zuweisen) **und** economy (buchen); die Settle-bei-
   Erledigung-Logik will umgekehrt von der Task-Erledigung getriggert werden.

## Entscheidung

1. **Escrow ausschließlich über das economy-Ledger (ADR-0035).** Konten `escrow:<listing_id>`.
   Listing = `member:seller → escrow:<id>` (deckungsgeprüft), Settle = `escrow → member:buyer`,
   Rückzug/Verfall = `escrow → member:seller`. **Kein gespeichertes Escrow-Feld** — der Stand ist die
   Ledger-Summe. So gilt automatisch „Σ inkl. Escrow konstant & nie negativ".
2. **Einseitige Abhängigkeit `marketplace → {tasks.api, economy.api}`.** marketplace nutzt
   `tasks.api.get_instance`/`reassign_instance` und `economy.api.transfer`/`escrow_account` — nie deren
   Interna. **Kein anderes Modul importiert marketplace** ⇒ kein Zyklus (import-linter erzwingt es).
   `task_instance_id` ist eine **reine ID** (kein Cross-Modul-FK).
3. **Settle ist in S8a explizit** (`POST /listings/{id}/settle`): liest die Instanz über `tasks.api`,
   und zahlt nur aus, wenn sie `done` ist (sonst 409). Das vermeidet die Gegenrichtung
   `tasks → marketplace` und damit den Zyklus. **Auto-Settle bei Erledigung** (event-getrieben) +
   **Auto-Accept-Regeln** + **Verfall→Rückfall-Cron** = **S8b** (über die Composition-Root-
   Handler-Registrierung bzw. einen `custode_maint`-Cron).
4. **Atomarität & Idempotenz:** jede Aktion ist eine Transaktion (Statuswechsel + Escrow-Buchung
   gemeinsam); die Statusmaschine (`open→accepted→settled` / `open→withdrawn`) mit 409-Wächtern
   verhindert Doppel-Settle/Doppel-Withdraw. Kein Doppel-Listing (offenes Listing je Instanz eindeutig).
5. **Kinder handeln nicht** (`require_role(admin, member)`; `marketplace_children` default off).

## Konsequenzen

- **Positiv:** Die Ökonomie-Invariante ist strukturell erfüllt (Escrow = Ledger-Konto). Saubere,
  zyklusfreie Modulgrenzen. Die Statusmaschine ist vollständig und property-getestet.
- **Negativ / Kosten:** Settle ist in S8a **manuell** (jemand drückt „Auszahlen", nachdem die Task
  erledigt ist) statt automatisch bei Erledigung — bewusst, um den Zyklus/das async Muster aus S8a
  herauszuhalten. Auto-Settle kommt in S8b. Bis dahin kann ein Escrow „hängen", bis jemand settlet
  (der Verkäufer/Käufer sieht das angenommene Listing mit „Auszahlen").

## Alternativen (verworfen)

- **`tasks.complete_instance` ruft `marketplace.api.settle(...)`** — synchron + automatisch, aber
  erzeugt `tasks → marketplace` **zusätzlich** zu `marketplace → tasks` = **Import-Zyklus**. Verworfen.
- **Kernel-Event-Handler settlet auf `task.completed`** — `kernel ↛ modules` (registry ist kernel-only,
  ADR-0035-Kontext). Geht nur über die Composition-Root-Registrierung (worker.py) = neues async Muster
  → in S8b, nicht S8a. Zurückgestellt.
- **Escrow als Spalte auf `market_listings`** — verletzt §5.9 (keine Saldo-Felder). Verworfen (Tabu).
