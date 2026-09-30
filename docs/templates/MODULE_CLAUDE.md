<!-- Vorlage für backend/app/modules/<name>/CLAUDE.md -->
# CLAUDE.md — Modul `<name>`

> Kurze Arbeitsanweisung für dieses Modul. Ergänzt die Root-`CLAUDE.md`.
> Bei Konflikt gilt: Sicherheit > KONZEPT/ADR > Root-CLAUDE.md > diese Datei.

## Zweck
Ein Satz: wofür ist dieses Modul zuständig? (Bezug: KONZEPT §5.x)

## Grenzen (hart)
- Importiert **nur** `kernel/*`, **nie** ein anderes Modul.
- Liest **keine** fremden Tabellen. Quermodul-Bedarf → Domain-Event oder das
  Service-Interface des Zielmoduls (`modules/<ziel>/api.py`).
- Jede Fachzeile trägt `household_id`; RLS-Policy + Negativtest pro Tabelle.

## Events
- **publiziert:** `…`
- **abonniert:** `…`

## Exportierte Services (`api.py`)
- `…` — Signatur + Zweck (das ist der einzige erlaubte synchron-Quereinstieg).

## No-Gos
- <modulspezifische Tabus, z. B. „keine Saldo-Felder", „kein PII in Logs">
