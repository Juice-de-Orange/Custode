# backend — Custode API

FastAPI Modular Monolith (Python 3.12+, uv-verwaltet). Struktur nach
`KONFIG/ARCHITECTURE.md §4`:

```
app/
├─ kernel/      geteilter Kern (KEINE Fachlogik): auth, tenancy, events, ports, db, http,
│               audit, config, crypto (ADR-0077), retention, sync, fetch.py (SSRF-Guard,
│               ADR-0030), redis.py, storage.py, images.py
├─ modules/     22 Fachmodule — importieren nur kernel/*, nie einander (import-linter)
├─ adapters/    Implementierungen der kernel/ports (echt + Null + Fake)
├─ scripts/     export_openapi, seed_demo, create_operator
├─ main.py settings.py logging.py telemetry.py worker.py
└─ *_factory.py  Port→Adapter-Auswahl am Composition Root (caldav, wearable, mail, issue)
```

## Entwicklung (ohne Docker)

```bash
uv sync
uv run python -m app.scripts.export_openapi     # erzeugt openapi.json
uv run ruff check .
uv run mypy                                      # files=["app"] steht in pyproject.toml
uv run pytest                                    # braucht Docker (Testcontainers: PG 18 + Redis)
uv run lint-imports                              # Modulgrenzen (27 Contracts)
uv run uvicorn app.main:app --reload            # http://localhost:8000/healthz
```

Einen Operator für die Betreiber-Konsole anlegen (kein Self-Service — die Konsole
reicht über alle Haushalte):

```bash
uv run python -m app.scripts.create_operator ops@example.org
```

Passwort aus `CUSTODE_OPERATOR_PASSWORD` oder generiert, TOTP-Secret immer generiert;
beide werden **einmalig** ausgegeben. Idempotent über die E-Mail. Ab `CUSTODE_ENV!=dev`
bricht das Skript mit Exit 2 ab, wenn `CUSTODE_DATABASE_URL_OPS_ACTIONS` fehlt — ein
Rückfall auf `custode_app` würde die Betreiber-Grenze (ADR-0071) still unterlaufen.

## Mit Docker (voller Stack)
Siehe Repo-Wurzel: `make dev`, `make migrate`, `make seed-demo`.

`make seed-demo` legt (nur bei `CUSTODE_ENV=dev`) einen einloggbaren Demo-Admin an —
`admin@custode.local` / `custode-admin-demo` — samt erfundenem, „bewohntem" Demo-Haushalt
(weitere Mitglieder, Rezepte, Wochenplan, Einkaufsliste, Aufgaben mit Punkten, Notizen,
Anleitung, Termine; alles über die Service-Funktionen der Module). Idempotent; gedacht für
die lokale Anmeldung ohne Registrierungs-/Mail-Flow und für Screenshots, nie für echte
Umgebungen.

Regeln: Modulgrenzen sind hart (import-linter). Jede Fachtabelle trägt
`household_id` + RLS (`kernel/db`, `kernel/tenancy`). Externe Grenzen nur über
`kernel/ports` mit Null-Adapter (Graceful Enhancement).
