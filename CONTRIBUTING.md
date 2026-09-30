# Contributing to Custode

Thanks for taking the time! Bug reports, translations, ideas and pull requests are welcome.
Larger changes are best discussed in an issue first — the product has a concept
(`KONFIG/KONZEPT.md`, German) and an architecture (`docs/ARCHITECTURE.md`, English) that changes
should fit.

## Before you start

- **`CLAUDE.md` is the binding working instruction** — for humans and AI-assisted sessions alike:
  module boundaries, the definition of done, the CI gates, the review rules. Read it first.
- **Concept first.** A new capability starts in `KONFIG/` (or an ADR in `docs/adr/`), then code
  (principle E9). Module boundaries are enforced by import-linter; do not work around them —
  build an event or an exported interface.
- **Every tenant boundary is an RLS policy with a negative test.** A new table gets a policy and a
  test that proves another household cannot read it.
- **Never hard-code the brand name** (`BRAND_NAME` only), never put contents, PII or secrets into
  logs, never store balances instead of ledger entries.
- Language: the concept and engineering docs are German by design; code identifiers, commit
  messages and this file are English; the UI ships in German and English.

## Development setup

```bash
cp .env.example .env
make dev && make migrate && make seed-demo   # full local stack (Docker)
make web                                     # Vite dev server
make lint && make lint-imports               # ruff, mypy --strict, eslint, tsc, import-linter
make test                                    # pytest (Testcontainers) + vitest — needs Docker, 10–30 min
```

Fast subset while iterating: `cd backend && uv run pytest tests/test_<module>*.py` and
`cd web && npm run test -- <pattern>`. The OpenAPI contract is generated: after changing an
endpoint run `make openapi` and commit `backend/openapi.json` and `web/src/api/`; CI fails on drift
and on breaking changes (`oasdiff`).

### Secret guard

Never commit a `.env`, a token, a real hostname or credentials. The gate runs gitleaks with the
repository's `.gitleaks.toml`; a [pre-commit](https://pre-commit.com/) hook is available:

```bash
pip install pre-commit && pre-commit install
```

## Branch and commit conventions

- Fork, then branch from `main`: `<kind>/<short-slug>`.
- Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/) with the module
  as scope where it applies: `feat(calendar): …`, `fix(accounts): …`, `docs: …`.
- Sign off your commits with the [Developer Certificate of Origin](https://developercertificate.org/):
  `git commit -s`. There is no CLA.

## Pull requests

- A bug fix comes with a regression test and, if it taught something, a `docs/BUGLOG.md` entry
  (cause, fix, regression test, lesson).
- All CI gates green: backend (ruff, mypy strict, import-linter, pytest), web (lint, typecheck,
  vitest, build, bundle-size, PWA, Lighthouse), contract (OpenAPI drift, oasdiff), security
  (gitleaks, trivy). A red gate is never "temporarily" disabled.
- Migrations are expand/contract and reversible; a new table comes with its RLS policy, grants for
  the four roles (`infra/postgres/init.sql` for dev) and a negative test.
- User-facing changes update the i18n catalogues in both languages and `CHANGELOG.md`.

## Licence

By contributing you agree that your contributions are licensed under the
[GNU AGPL-3.0](LICENSE).
