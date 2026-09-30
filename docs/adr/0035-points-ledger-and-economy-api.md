# ADR-0035: Punkte-Ledger — Modell & synchrone Gutschrift via economy.api

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `modules/economy` (neu), `modules/tasks`, `kernel/events` · **Bezug:** KONZEPT §5.9/§5.10/§10, ARCHITECTURE §4 (Modulgrenzen), §8 (Outbox), Roadmap Phase 4
- **Bezug ADRs:** ADR-0034 (tasks: task.completed), ADR-0031 (Cross-Modul via api.py: recipes→nutrition)

## Kontext

Phase 4 braucht die Punkte-Ökonomie (KONZEPT §5.9): ein **append-only Doppelbuchungs-Ledger**
(Salden sind Summen, nie editierbar; `amount > 0`; keine negativen Salden; jede Bewegung referenziert
ein Fachereignis). Erste Quelle: Task-Erledigung (System → Mitglied). Spätere Senken/Transfers:
Belohnungs-Einlösung (Mitglied → System), Marketplace-Escrow (Mitglied → `escrow:<listing_id>` →
Käufer), Danke-Punkte (Mitglied → Mitglied).

`tasks` emittiert bereits `task.completed` (ADR-0034). Die naheliegende Frage: bucht ein
**Outbox-Event-Handler** asynchron ins Ledger, oder bucht `tasks` **synchron** in derselben Transaktion?

Harte Randbedingung: Das Event-Handler-Registry (`kernel/events/registry.py`) ist **bewusst
kernel-only** — „feature modules only emit events; their handlers live in the kernel". `kernel` darf
`modules` nicht importieren (import-linter). Ein Ledger-Handler im Kernel müsste also die Ökonomie-Logik
(Deckungsprüfung, Doppelbuchung, Konten) im Kernel duplizieren — eine Schichtverletzung (Kernel = Infra,
keine Fachlogik/Fachdaten).

## Entscheidung

1. **Neues Fachmodul `economy`** besitzt das Ledger (Tabelle `points_ledger`, KONZEPT §10) und die
   Buchungslogik. Konten sind Strings: `system`, `member:<uuid>`, `escrow:<uuid>`. Eine Bewegung =
   eine Zeile `(from_account, to_account, amount>0, ref_type, ref_id, created_by, …)`. **Append-only**
   (kein UPDATE/DELETE im Code; Korrektur = neue Gegenbuchung `ref_type=admin_correction`). Saldo eines
   Kontos = `Σ(to=konto) − Σ(from=konto)` — nie ein gespeichertes Feld.
2. **Gutschrift = synchron via `economy.api`** in **derselben Transaktion** wie das auslösende
   Fachereignis: `tasks.complete_instance()` ruft `economy.api.credit_task_completion(...)` (Kette
   `system → member:done_by`). Vorbild: `recipes`→`nutrition.api` (ADR-0031), erlaubt per CLAUDE.md
   („Quermodul nur über Events **oder** exportierte Service-Interfaces"). `economy` importiert **nie**
   ein anderes Modul; die Abhängigkeit ist strikt einseitig `tasks → economy.api`.
3. **`task.completed` bleibt** als Domain-Event für **entkoppelte** Konsumenten (SSE-Invalidation,
   später Notifications/Digest/Fairness) — nur die **Ledger-Gutschrift** läuft synchron.
4. **Keine negativen Salden:** vor jeder Senke mit Mitglied-/Escrow-Quelle prüft `economy.api` die
   Deckung (`balance(from) ≥ amount`), sonst Fehler (422) statt Buchung. Das `system`-Konto schöpft
   (keine Deckungsprüfung).

## Konsequenzen

- **Positiv:** Buchung **atomar** mit der Erledigung (Commit/Rollback gemeinsam) und **exakt-einmal**
  — die Idempotenz liefert der bestehende 409-Wächter der Erledigung (`open→done` nur einmal). **Saldo
  sofort** sichtbar (kein Worker-Lag). Kein Kernel-Schichtbruch. Konsistent mit dem etablierten
  `*.api`-Quermodul-Muster. Ledger ist auditierbar (append-only) und reparierbar (Gegenbuchung).
- **Negativ / Kosten:** bewusste **Abweichung vom rein eventgetriebenen KONZEPT-Wortlaut** („task.completed
  → Ledger"), dokumentiert nach Prinzip E9 (erst ADR, dann Code). Eine Erweiterung auf asynchrone
  Buchung (falls je nötig) müsste die Composition-Root-Registrierung (worker.py importiert Modul-Handler)
  einführen — heute nicht nötig.
- **Auswirkungen:** Migration 0024 (`points_ledger` + RLS + Negativtest); import-linter: `tasks →
  economy.api` erlaubt, `economy → andere Module` verboten, andere Module ↛ `economy.*` außer via api.
  Property-Tests für die Invarianten (Saldo = Σ; nie negativ; Transfer summenerhaltend).

## Alternativen (verworfen, mit Begründung)

- **Outbox-Event-Handler im Kernel** bucht auf `task.completed` — entkoppelt, aber `kernel` dürfte
  `modules.economy` nicht importieren ⇒ Ökonomie-Logik müsste in den Kernel (Schichtbruch) **oder** als
  Roh-SQL dupliziert werden; zudem eventual-consistent (Saldo erst nach Worker sichtbar). Verworfen.
- **Composition-Root registriert Modul-Handler** (`worker.py` importiert `economy`-Handler, hängt ihn an
  den Dispatcher) — sauber bzgl. Grenzen, aber neues Muster + Async-Lag ohne Mehrwert für eine Buchung,
  die ohnehin in der Erledigungs-Tx passieren kann. Zurückgestellt (einführbar, wenn ein echter
  asynchroner Konsument es braucht).
- **Saldo-Feld auf `memberships`** statt Ledger — verletzt §5.9 (Salden = Summen, nicht editierbar) und
  macht Audit/Reparatur unmöglich. Verworfen (Tabu).

## Nachtrag 11-S1b (2026-07-31) — der zurückgestellte Fall ist eingetreten

Die dritte verworfene Alternative oben — „Composition-Root registriert Modul-Handler" — war nicht
verworfen, sondern **zurückgestellt**: *„einführbar, wenn ein echter asynchroner Konsument es
braucht."* Der Konsument ist da. Der **Austritt aus einem Haushalt** (KONZEPT §5.1) berührt
Marketplace, Tasks und Economy in **fester Reihenfolge**, und kein Modul darf ein anderes
importieren — jeder Versuch, die Abfolge innerhalb eines Moduls zu orchestrieren, wäre eine
Grenzverletzung. Sie lebt deshalb in `app/member_exit.py` am Composition Root, gebunden an
`member.left`.

Zwei Festlegungen, die den Ledger betreffen:

**Verfall ist eine Buchung, keine Löschung.** Restpunkte einer ausscheidenden Person gehen per
`transfer` nach `system`, `ref_type='member_exit'` (KONZEPT §5.1 legt den Wert wörtlich fest). Die
Begründung folgt direkt aus Punkt 1 dieses ADR: Salden sind **Summen**. Wer die Zeilen einer Person
entfernte, veränderte damit die Salden **anderer** — ein Danke-Punkt `member:A -> member:B` gehört
beiden Seiten — und könnte sie unter null drücken. Die Invariante „keine negativen Salden" wäre
gebrochen, ohne dass die Betroffenen etwas getan hätten. Append-only ist hier kein Selbstzweck,
sondern der einzige Weg, der die Summen anderer unangetastet lässt.

**Die Reihenfolge gehört zur Korrektheit.** Handelspositionen werden **vor** dem Verfall aufgelöst.
Andersherum käme freigegebenes Escrow nach dem Verfall auf dem Konto an und läge dort für immer:
`withdraw_listing` prüft `seller_id`, und die Person ist dann keine mehr — es gäbe keine Route, die
das Guthaben je wieder bewegte. Negativprobiert (`tests/test_member_exit_economy.py`): mit
umgedrehter Reihenfolge bleiben 30 Punkte auf einem Konto ohne Person liegen.

Dabei entstand `marketplace.revert_listing` und damit der erste Codepfad zum Zustand `reverted`,
der seit Migration 0028 im CHECK stand und nie erreichbar war.
