<!-- Vorlage für docs/MODULES/<name>.md — Doku für Mensch UND KI -->
# Modul `<name>`

**Status:** geplant | in Arbeit | stabil · **Phase:** <n> · **KONZEPT:** §5.x

## Zweck & Verantwortung
Was leistet das Modul, was bewusst nicht?

## Datenobjekte
Tabellen/Entitäten mit Schlüsselfeldern und Invarianten (Bezug KONZEPT §10).

## Schnittstellen
- **Events out / in:** …
- **Services (`api.py`):** …
- **Ports genutzt:** … (immer mit Null-Adapter-Pfad, P5)

## AuthZ-Matrix
| Aktion | admin | member | child | guest | fremder Haushalt |
|---|---|---|---|---|---|
| `<aktion>` | ✓ | ✓ | ✗ | ✗ | **immer ✗** (RLS-Negativtest) |

## Zustände & Fehler
Statusmaschinen, Fehler-Referenzcodes (siehe `docs/errors.md`), Empty/Loading/Error.

## Tests
Unit · Integration (Persistenz/Events/RLS-Negativ) · e2e · Property-Tests (falls
Invarianten). Beide Pfade bei Enhancement (P5).

## Offene Punkte
- …
