# ADR-0070 — Wochen-Digest: haushaltsübergreifender E-Mail-Fan-out unter der maint-Rolle

**Status:** beschlossen · **Phase:** 8 (P8-S7) · **Datum:** 2026-06-29
**Kontext-KONZEPT:** §5.12 (Messaging/Notifications, E-Mail-Digest), `ENTWICKLUNGSKONZEPT` P5
(Graceful Enhancement) & P1 (Ruhe statt Lärm), `ARCHITECTURE` §8.4 (Worker-Crons) + §9
(haushaltsübergreifende Wartungs-Jobs laufen unter separater DB-Rolle). Roadmap Phase 8 („Week-Digest").

## Kontext
Die F&F-Beta soll einen ruhigen wöchentlichen Überblick per E-Mail bekommen. Das ist der **erste**
proaktive Benachrichtigungskanal und der erste Job, der **über alle Haushalte** iteriert und dabei
Mitglieder-**E-Mail-Adressen** (PII) verarbeitet. Zwei Spannungen: (a) Modulgrenzen — der Digest liest
Aufgaben **und** Konten, darf aber keine fremden Tabellen lesen; (b) RLS — ein haushaltsübergreifender
Job kann nicht unter der app-Rolle laufen (die sieht nur den aktiven Haushalt).

## Entscheidung

### Eigenes Logik-Modul `digest` (keine Tabelle, kein Router)
`modules/digest` ist reine Orchestrierung. Es importiert **nur** die öffentlichen APIs
`accounts.api` (Empfänger) und `tasks.api` (offene/überfällige Zähler) — nie deren Interna, nie eine
fremde Tabelle (import-linter: „digest uses only accounts/tasks public api"). Kein Modul importiert
`digest`; einzig der Worker-Composition-Root ruft `send_weekly_digests`.

### Fan-out unter der maint-Rolle, mit explizitem `household_id`-Filter
Die Worker-Cron (`send_weekly_digest_job`, Mo 07:00) öffnet eine **maint-Session**
(`get_maint_sessionmaker`). `accounts.api.list_digest_recipients` zählt auf die bestehenden
maint-Lesepolicies (Migrationen 0006/0007: `maint_all USING(true)` + SELECT auf
`households`/`memberships`/`users`). **Wichtig:** weil `maint_all` *alle* Haushalte sichtbar macht,
filtern die Zähl-Queries (`tasks.api.count_open_tasks`) `household_id` **explizit** — RLS trägt hier
nicht. Empfänger = Mitglieder mit Rolle `admin`/`member` **und** E-Mail; **Kinder und Gäste sind
ausgeschlossen** (KONZEPT „Kinder & Sicherheit"; Kinder haben ohnehin keine E-Mail).

### Graceful Enhancement (P5)
Versand über `MailPort`, erzeugt aus `app.mail_factory.build_mail` (geteilt mit `main.py`). Ohne
SMTP greift der **Null-Adapter**: er akzeptiert, sendet aber nichts — die App ist unbeeinflusst.
Beide Pfade sind getestet (`tests/test_digest.py`).

### Opt-out je Haushalt
Gelesen aus `households.settings_json['digest_enabled']` (Default **an**). Der Reader liegt im
Digest-Service; die Admin-Umschaltung (Endpoint + UI) ist die Folge-Slice **P8-S7b**.

### P1/Privacy
Keine PII in Logs — nur ein Aggregat-Zähler (`weekly_digest_sent`, Anzahl). Der Mail-Body enthält nur
**eigene** Aggregate des Haushalts (offene/überfällige Aufgaben), keine personenbezogenen Details.
Marketingname nur via `settings.brand_name` (nicht hartcodiert).

## Konsequenzen
- **Plus:** Modulgrenzen bleiben sauber (zwei `api.py`-Importe, keine Fremd-Tabelle); der maint-Fan-out
  wiederverwendet das etablierte Cross-Household-Lesemuster (0006/0007) und das Cron-Muster der Reaper.
- **Plus:** Voll graceful — ohne SMTP passiert schlicht nichts; kein Pflicht-Infra.
- **Minus:** Inhalt v1 ist nur die Aufgaben-Zusammenfassung; **Mahlzeiten/weitere Module** folgen als
  spätere Slice (zusätzliche `api.py`-Zähler).
- **Minus:** Kein Push/Inbox-Kanal in diesem Slice (nur E-Mail-Digest) und keine P1-Budget-Bündelung
  über mehrere Kanäle — die volle `NOTIFICATIONS.md`-Matrix wächst mit den weiteren Kanälen.
- **Offen:** personalisierter Pro-Mitglied-Digest, Web-Push, Abmelde-Link je Mail, Lokalisierung
  (heute Deutsch).

## Alternativen
- **Digest-Logik im Worker/Composition-Root:** vermischt Geschäftslogik mit der Worker-Verdrahtung;
  verworfen zugunsten eines testbaren Logik-Moduls.
- **Pro Haushalt eine app-gescopte Session:** die app-Rolle kann Haushalte nicht aufzählen (RLS);
  verworfen — maint + expliziter Filter ist das §9-Muster.
- **`digest_enabled` als Feature-Flag (`flags.py`):** Flags modellieren Modul-an/aus, nicht
  Notification-Präferenzen; getrennt gehalten in `settings_json` (eigener Schlüssel).
