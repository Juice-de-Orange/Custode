# Modul `digest`

**Zweck:** Wöchentlicher Haushalts-Überblick per E-Mail (Roadmap Phase 8, P8-S6, ADR-0070). Ein
**Logik-Modul** ohne Tabelle/Router — die Worker-Cron ruft `send_weekly_digests` unter der
**maint-Rolle** (haushaltsübergreifend, ARCH §9).

## Aufbau
- `service.py` — `send_weekly_digests(session, *, mail, brand, now)`: pro Haushalt (nicht abgemeldet,
  ≥1 Empfänger) Zusammenfassung komponieren und via `MailPort` versenden. Gibt die Zahl der vom
  Adapter akzeptierten Mails zurück.
- `api.py` — exportiert `send_weekly_digests` (einzige Naht; nur der Worker ruft sie).
- Keine Models, keine Migration, keine HTTP-Routen.

## Datenquellen (nur öffentliche APIs)
- `accounts.api.list_digest_recipients(session)` → je Haushalt `(household_id, name, settings_json,
  recipient_emails)`; erwachsene Mitglieder (`admin`/`member`) mit E-Mail; **maint-Lesepolicies**
  (Migrationen 0006/0007).
- `tasks.api.count_open_tasks(session, *, household_id, now)` → `(open, overdue)`, **explizit** nach
  `household_id` gefiltert (maint sieht alle Haushalte — RLS trägt nicht).

## Versand & Graceful Enhancement
- `MailPort` aus `app.mail_factory.build_mail` (geteilt mit `main.py`). Ohne SMTP → Null-Adapter
  akzeptiert, sendet aber nichts (Basis-Pfad). Beide Pfade getestet (`tests/test_digest.py`).
- Worker-Cron: `app/worker.py::send_weekly_digest_job` (`0 7 * * 1`, Mo 07:00).

## Opt-out
- `households.settings_json['digest_enabled']` (Default an). Reader im Service; Admin-Umschaltung über
  `accounts` (`GET/PATCH /v1/household/digest`) + `DigestToggle` im Web (P8-S7b).

## Events
- Publiziert/abonniert: keine (Cron-getrieben).

## Tests
- `tests/test_digest.py` — Empfänger nur opt-in & erwachsen & mit E-Mail (Kind/opt-out ausgeschlossen),
  korrekte Aufgaben-Zusammenfassung; **Graceful**: läuft fehlerfrei durch den Null-Adapter.

## No-Gos
- **Kein PII/Inhalt in Logs** — nur Aggregat-Zähler. E-Mail-Adressen nie loggen.
- Nie eine fremde Tabelle lesen — nur `accounts.api`/`tasks.api`.
- `household_id` in den Zähl-Queries **immer** explizit filtern (maint umgeht RLS).
