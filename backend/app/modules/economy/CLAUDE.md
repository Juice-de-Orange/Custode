# CLAUDE.md — Modul `economy`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Punkte-Ökonomie des Haushalts (KONZEPT §5.9): **append-only Doppelbuchungs-Ledger** (`points_ledger`).
Quelle Task-Erledigung; spätere Senken/Transfers: Belohnungen, Marketplace-Escrow, Danke-Punkte.
P4-S2 = Ledger + Saldo-Lesepfad + synchrone Gutschrift bei Task-Erledigung.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, **nie** ein anderes Modul (import-linter: `economy ↛ modules`).
  Andere Module buchen ausschließlich über `economy/api.py` (synchron, ADR-0035) oder reagieren auf
  Events. `economy` liest **keine** fremden Tabellen.
- `points_ledger` trägt `household_id`; RLS aktiv (`FORCE`), Negativtest.

## Datenmodell (Migrationen 0024 + 0025)
- `points_ledger` (0024): `from_account, to_account, amount(>0, CHECK), ref_type, ref_id?, note?,
  created_by?` (+ Standard-Mixin). Konten: `system`, `member:<uuid>`, `escrow:<uuid>`. **Append-only**
  (nie UPDATE/DELETE; Korrektur = Gegenbuchung `ref_type=admin_correction`).
- `rewards` (0025): admin-Katalog (`cost>0`, optional `stock`/`cooldown_hours`, `version`=ETag,
  Soft-Delete). `redemptions` (0025): Einlösung (`title`/`cost` Snapshot, Status `requested→fulfilled`,
  nie hard-deleted). Einlösen bucht synchron `transfer(member→system)` (Deckung) + Stock/Cooldown.

## Invarianten (KONZEPT §5.9 — Tabu bei Verletzung)
- **Salden sind SUMMEN** (`Σ to − Σ from`), nie ein gespeichertes/editierbares Feld.
- `amount > 0` je Zeile (DB-CHECK + Service).
- **Keine negativen Salden:** vor jeder Senke mit Mitglied-/Escrow-Quelle Deckungsprüfung
  (`balance(from) ≥ amount`) → sonst 422. Nur `system` schöpft ohne Deckung.
- Jede Bewegung referenziert ein Fachereignis (`ref_type`/`ref_id`).

## Schnittstellen
- **HTTP `/v1/economy`:** `GET /balance` (eigener Saldo) · `GET /ledger?limit=` (eigene Bewegungen,
  neueste zuerst) · `POST /corrections` (**admin**, CSRF; Grant/Claw-back als sichtbare Gegenbuchung).
- **Services (`api.py`):** `balance`, `transfer`, `credit_task_completion`, `member_account`,
  `escrow_account`, `fairness_load`, `expire_member_balance`. **`transfer` ist der einzige
  Schreibpfad** — Deckungsprüfung inklusive.

## Austritt: Verfall ist eine BUCHUNG, keine Löschung (11-S1b, KONZEPT §5.1)
- `expire_member_balance` bucht den Restsaldo nach `system`, `ref_type='member_exit'` (im KONZEPT
  wörtlich so festgelegt). Gibt den verfallenen Betrag zurück; Saldo ≤ 0 ⇒ No-Op (idempotent).
- **Warum nicht löschen:** jede Buchung hat zwei Konten. Wer die Zeilen einer Person entfernte,
  veränderte damit die Salden **anderer** — ein Danke-Punkt `member:A -> member:B` gehört beiden
  Seiten — und könnte sie unter null drücken. „Keine negativen Salden, nirgends" wäre gebrochen,
  ohne dass die Betroffenen etwas getan hätten.
- **Muss nach dem Auflösen der Handelspositionen laufen.** Sonst kommt freigegebenes Escrow nach
  dem Verfall an und liegt für immer auf einem Konto, das keine Route mehr auflöst. Die Reihenfolge
  steht in `app/member_exit.py` — sie ist dort der Inhalt, nicht die Verpackung.

## Events
- **publiziert:** `reward.changed`, `reward.redeemed` → SSE-Entity `"rewards"`; `thanks.sent` →
  `"economy"` (Saldo + Challenge live). Die Ledger-Buchung selbst ist synchron (kein Event);
  Saldo/Challenge-SSE auch über den `tasks`-Hint.
- **Danke-Punkte/Challenge/Fairness:** `send_thanks` (member→member, Deckung + Wochen-Cap 10/ISO-Woche),
  `weekly_challenge` (Live-Rollup der Woche), `fairness_load` (30-Tage-Last, aufsteigend; `api.py`-Export
  als Marketplace-Tiebreaker). Alles live aus dem Ledger — kein DB-Zähler.
- **abonniert:** — (`economy` reagiert nicht auf fremde Events; Aufrufer buchen synchron via api.py).

## No-Gos
- **Niemals ein Saldo-Feld** auf Mitgliedschaften/Usern (Tabu §5.9). Saldo immer aus dem Ledger summieren.
- **Nie UPDATE/DELETE** auf `points_ledger` (append-only); Korrektur nur als Gegenbuchung.
  **Eine benannte Ausnahme:** der Haushalts-Purge (`app/household_deletion_policy.py`, 11-S1f,
  ADR-0086 §6) leert den Ledger, wenn der **Mandant endet**. Das weicht die Regel nicht auf — sie
  schützt die Salden *anderer* Konten, und nach der Auflösung gibt es keine. Wer aus einem anderen
  Grund löschen will, hat die Regel gebrochen. **Achtung:** die Datenbank erzwingt das append-only
  hier **nicht** (volles DELETE-Recht, `ALL`-Policy für `custode_app`) — anders als bei `consents`,
  wo Migration 0013 nur `SELECT, INSERT` vergibt. Die Regel hängt allein an diesem Absatz; ein
  eigener Roadmap-Punkt führt das.
- **Nie negative Salden** zulassen (Deckungsprüfung).
- **Punkte ↛ Geld** (N-1): keine Umrechnung, strikt getrennt vom späteren Finanzen-Ledger.
