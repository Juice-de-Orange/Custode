# CLAUDE.md — Modul `digest`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Wöchentlicher Haushalts-Überblick per E-Mail (Roadmap Phase 8, „Week-Digest"). **Logik-Modul** ohne
Tabelle/Router: die wöchentliche Worker-Cron ruft `send_weekly_digests` unter der **maint-Rolle**
(haushaltsübergreifend, ARCH §9). P8-S6 = Fundament: Zusammenfassung der offenen/überfälligen Aufgaben
je Haushalt, an alle erwachsenen Mitglieder mit E-Mail. Mahlzeiten-Zusammenfassung = spätere Slice.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + die **öffentlichen APIs** `accounts.api` (Empfänger) und `tasks.api`
  (Aufgaben-Zähler) — nie deren Interna, nie eine fremde Tabelle (import-linter: „digest uses only
  accounts/tasks public api"). Kein Modul importiert `digest` (nur der Worker-Composition-Root ruft es).
- **Keine eigene Tabelle, kein Router** — reines Orchestrierungs-Service.

## Graceful Enhancement (P5)
- Versand über `MailPort`. **Null-Adapter** → nichts wird gesendet, App unbeeinflusst (Basis-Pfad).
  **SMTP** → jede erwachsene Mitglied-Adresse erhält die Zusammenfassung. Beide Pfade getestet.

## Opt-out
- Pro Haushalt über `households.settings_json['digest_enabled']` (Default **an**). Der Reader liegt
  hier; die Admin-Umschaltung läuft über `accounts` (`GET/PATCH /v1/household/digest`, P8-S7b) +
  `DigestToggle` im Web.

## No-Gos
- **Kein PII/Inhalt in Logs** — nur Aggregat-Zähler (gesendete Mails). E-Mail-Adressen nie loggen.
- `digest` schreibt nichts in fremde Module; liest Aufgaben/Empfänger nur über deren `api.py`.
- `household_id` wird in den Zähl-Queries **explizit** gefiltert (maint sieht alle Haushalte — RLS
  trägt hier nicht).
