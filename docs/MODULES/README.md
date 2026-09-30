# MODULES — ein Dokument je Fachmodul

Je Modul aus `backend/app/modules/<name>/` liegt hier `‹name›.md` (Vorlage:
[`../templates/MODULE_DOC.md`](../templates/MODULE_DOC.md)). Es beschreibt Zweck,
Datenobjekte, Events/Services, AuthZ-Matrix und Tests — für Menschen **und** KI
(ENTWICKLUNGSKONZEPT Teil C/D).

Module entstehen ab **Phase 1** (Roadmap); Stand Phase 9 sind es **22**. Die
Modulgrenzen erzwingt der import-linter in der CI (27 Contracts) — ein Modul
importiert nur `kernel/*` und die `api.py` fremder Module, nie deren Internas.

## Wer eine Tabelle mit `household_id` anlegt, ordnet sie in **drei** Listen ein

Das ist die Regel, die man am leichtesten übersieht und die am teuersten ist:

| Liste | Was sie beantwortet | Was passiert, wenn sie fehlt |
|---|---|---|
| `app/export_policy.py` | Kommt die Tabelle in den Datenexport (Art. 15/20)? | **CI wird rot** (zwei Gates, eines gegen die echte DB) |
| `app/deletion_policy.py` | Was wird aus ihren Zeilen bei einer **Konto**-Löschung — je **Spalte** | **CI wird rot** (Gate gegen die echte DB) |
| `app/household_deletion_policy.py` | Fällt sie beim **Haushalts**-Purge — je **Tabelle** | **CI wird rot** — und der Job um 04:00 fällt in Produktion mit `UnclassifiedTableError` **geschlossen** aus: er löscht dann nichts, statt zu raten |

Die dritte ist die stille: **kein Fremdschlüssel zeigt auf `households.id`**, die Datenbank kann
eine vergessene Tabelle also nie melden (ADR-0086). Deshalb leitet der Purge seine Menge aus dem
Katalog ab und verlangt für jede gefundene Tabelle eine Entscheidung.

**Mitglieds-gescopte Tabellen brauchen dagegen nichts Zusätzliches.** Der Haushalts-Purge
wiederholt seinen Durchgang ohnehin je Mitglied, genau damit hier keine zweite Liste entsteht,
die veralten kann.

## Index (22 Module)

| Modul | Zweck | Phase |
|---|---|---|
| [accounts](accounts.md) | Identität, Haushalte, Mitgliedschaften, Rollen, Auth | 1 |
| [recipes](recipes.md) | Rezept-CRUD, Import (JSON-LD/Scraper/LLM), Kochmodus | 2 |
| [nutrition](nutrition.md) | Kanonische Zutaten, Nährwertberechnung | 2 |
| [shopping](shopping.md) | Einkaufsliste, Quick-Katalog, Sync-Batch (offline) | 3 |
| [tasks](tasks.md) | Haushaltsaufgaben, Zustandsmaschine, Wert-Verfall, Räume | 4 |
| [economy](economy.md) | Punkte-Ledger (append-only Doppelbuchung), Rewards | 4 |
| [marketplace](marketplace.md) | Aufgaben-Handel via Escrow über das Ledger | 4 |
| [capture](capture.md) | Zuruf — Regel-Parser + optionale LLM-Anreicherung | 4 |
| [calendar](calendar.md) | Persönlicher/Haushalts-Kalender, RRULE, ICS, Layer | 5 |
| [scheduling](scheduling.md) | Slot-Vorschläge (read-only) über calendar.api | 5 |
| [weather](weather.md) | Open-Meteo + Null-Adapter (Graceful Enhancement) | 5 |
| [mealplanner](mealplanner.md) | Wochenplan + Auto-Füllen (nährwert-/abwesenheitsbewusst) | 6 |
| [messaging](messaging.md) | Briefe (asynchron, Gelesen-Status) | 7 |
| [guides](guides.md) | Anleitungen, deutsche FTS, Anhänge, Ansprechpartner | 7 |
| [notes](notes.md) | Notizen, Versions-Historie, Papierkorb/Restore | 7 |
| [comments](comments.md) | Generische Objekt-Threads `(object_type, object_id)` | 7 |
| [links](links.md) | Generische, richtungsunabhängige Objekt-Verknüpfungen | 7 |
| [vault](vault.md) | Clientseitig E2E-verschlüsselter Tresor (Server: Ciphertext) | 7 |
| [feedback](feedback.md) | F&F-Feedback-Kanal an den Betreiber (RLS) | 8 |
| [digest](digest.md) | Wöchentlicher E-Mail-Überblick (Logik-Modul, maint-Fan-out) | 8 |
| [backoffice](backoffice.md) | Betreiber-Konsole `/ops` (Auth, KPIs, Aktionen, nur Aggregat-Views) | 8 |
| [wearables](wearables.md) | Wearable-Clouds (Oura), Art.-9-Consent, mitglieds-gescopte RLS | 9 |

Geplant (noch ohne Modul-Doku): `billing`/`finance` (Phase 12+).
