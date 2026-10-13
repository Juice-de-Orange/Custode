# Changelog

All notable changes to Custode. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The pre-release engineering
history (June–September 2026, German) is not part of the public repository.

## [Unreleased]

### Changed

- Bundle budget of the member app raised from 231 to 235 kB (gzip, eager JS + CSS): v0.1.1 left 1 byte,
  which blocked every visible dependency update.

## [0.1.1] - 2026-10-13

Fixes from the first-visitor check: the offline shopping list now works offline end to end, an
instance without SMTP says so instead of claiming to send mail, and signing in lands on Today.

### Fixed

- The shopping list works offline as promised: items added or checked off without a connection are
  saved on the device and queued, the list opens after a reload or restart while still offline,
  and everything syncs when the connection returns. Before, offline changes were held only in
  memory and an offline reload hung at "Loading …" and lost them.
- Without SMTP the account page no longer claims "Verification e-mail sent.": it says that this
  server does not send e-mail. `/v1/auth/me` reports `mail_enabled`, and a resend answers
  `503 mail_unavailable`.
- Signing in lands a household member on Today instead of the account page.
- `/v1/demo` answers `{"enabled": false}` on a normal instance instead of a 404 on every page load.

### Changed

- README: the first run says where the household is created (the account page after sign-up, or
  join one with an invite code), and the quick-start time is measured with the published images.
- The issue chooser links to GitHub Discussions for questions and ideas.
- CI has an `e2e` job: a Playwright test of the offline shopping list (`web/e2e`) against the
  quick-start stack built from the commit; `CONTRIBUTING.md` says how to run it locally.
- Dependencies: FastAPI 0.143, Pydantic 2.14, asyncpg 0.32, OpenTelemetry 1.45.1 and
  uuid-utils 1.0 in the backend; Lingui 6 in the web app. Development only: jsdom 30,
  jest-dom 7, ruff 0.17, mypy 2.4.

## [0.1.0] - 2026-10-12

The first public release of Custode, under AGPL-3.0. It is a beta: see the README's status box
for what was checked and what was not.

### Added

- Initial public release under AGPL-3.0: all modules of roadmap phases 0–9 (accounts and
  households, recipes and nutrition, meal planner, shopping list, calendars with CalDAV sync,
  tasks with points ledger and marketplace, vault, messaging, guides, notes, comments, wearables,
  weather, quick-capture), the operator console, GDPR export and erasure with purge jobs.
- Public demo mode (`CUSTODE_DEMO_MODE=on`, default off): one shared demo household whose login
  the sign-in page fills in, a banner on every page (English and German), sign-up, mail, invites,
  uploads, imports, ICS/CalDAV, vault, integrations, the live stream and the operator console
  refused server-side with `demo_disabled`, every external adapter off, a per-visitor rate limit,
  a body cap and `noindex`. `docker-compose.demo.yml` runs it isolated (internal network without
  internet for the app, one port on `127.0.0.1`, limits per service, rotated logs), and
  `python -m app.scripts.demo_reset` puts the household back every hour. The demo seed has an
  English variant (`python -m app.scripts.seed_demo --lang en`). See `docs/demo.md`.
- Source-code link in the app footer (AGPL §13), English `README.md` and `docs/ARCHITECTURE.md`,
  contributor documentation, hardened CI, CodeQL, Dependabot.
- A lived-in demo household for `make seed-demo`.
- The English interface is reachable: the UI follows the browser language (English as fallback)
  and can be pinned per browser under Profile → Language.
- The account page shows admins the sign-in link for child accounts, with a copy button.
- `docs/operations.md`: the operator guide in English — install, configure, reverse proxy, legal
  pages, backup, restore, update (with draining the job queue first), logs and health.
- The `web` service has the network alias `custode-web`: point your proxy at `custode-web:80`,
  independent of the Compose project name.
- One-command start: `./setup` writes `.env` with generated secrets, `docker compose up -d` runs
  the stack on `http://localhost:8080` (`docker-compose.quickstart.yml`), and
  `docker compose run --rm seed-demo` adds a sample household without any host toolchain.
- Release workflow: every `v*` tag publishes `ghcr.io/juice-de-orange/custode-api` and
  `custode-web` for linux/amd64 and linux/arm64; `docker-compose.prod.yml` pulls them and keeps
  `build:` as the fallback. A `migrate` job applies the migrations before the app starts.
- Issue template for questions; README hero animation and "How it compares".

### Changed

- The interface falls back to English (was German) when the browser asks for neither language;
  the installable app's manifest, the page language and the screen-reader labels of the
  navigation are English by default. `.env.prod.example` and the comments in
  `docker-compose.prod.yml` are English.
- README: the tagline says "self-hosted" instead of "EU-hosted" (there is no hosted service);
  quick-capture is described as it works (deterministic parsing, an optional local LLM enriches
  free text); a "Known limitations" section.
- Imprint and privacy policy come from the operator: Markdown files in the `legal/` folder
  (`imprint.md`, `privacy.md`, optionally per language), served by the `web` container under
  `/legal/`. Without them the pages say that the operator has not provided them; the draft texts
  that every instance used to ship as its own are gone. `legal/privacy.example.md` is a template
  (see `docs/operations.md`, "Legal pages"). `CUSTODE_LEGAL_DIR` points the stack at another
  folder.
- The footer's "Source code" link (AGPL §13) can point at a modified version's source:
  `CUSTODE_SOURCE_URL` in `.env`, applied at the next `build`.
- A child account is no longer asked to confirm an e-mail address it does not have, and `/vault`
  tells child and guest accounts that the vault is not available to them.
- README: what the functional checks covered and what they did not; the backup section names the
  one visible effect of not restoring Redis.
- Production deployment files are generic templates (`docker-compose.prod.yml`,
  `.env.prod.example`, `infra/postgres/init.prod.sh`, `infra/caddy/Caddyfile`); the deploy job
  is not part of the public CI.
- Problem-type URIs point at the error catalogue in this repository.
- Web: React 19.3. The API client is generated into `web/src/api/client` and `web/src/api/core`
  by `@hey-api/openapi-ts` 0.99 instead of being imported from `@hey-api/client-fetch`. Bundle
  budgets: member app 231 kB, operator console 147 kB (gzip, eager JS + CSS).
- Calendar API: event times in request bodies must carry a time-zone offset (`starts_at`/`ends_at`
  on create and PATCH, `occurrence_start`/`new_start`/`new_end` on the occurrence endpoints);
  otherwise `422 validation`. **Behaviour change for API clients:** a create or PATCH with a naive
  pair, and a restore/reset with a naive `occurrence_start`, used to succeed with the value read as
  UTC. The web app always sends offsets and is not affected.
- E-mails (verification, password reset, weekly digest) are written in the recipient's account
  language — German for a German locale, English otherwise — instead of always German. The web
  app stores the interface language on the account at registration and on a change in the
  profile.
- API problem responses have English `title` and `detail` texts (slugs unchanged; the web app
  translates by slug as before), and `docs/errors.md` is in English.

### Fixed

- `create_operator` works in the dev stack: the dev api now connects with the operator roles
  (`ops_readonly`, `ops_actions`) like production; before, it failed with "permission denied for
  table operators".
- Vault: an entry your key cannot decrypt is shown as "Unreadable entry" with an explanation
  instead of "??", and deleting it asks for confirmation first — another member may still be
  able to read it. Readable entries keep their direct delete button.
- Vault: an outdated app (for example an old build still served by an installed PWA) can no
  longer store a passphrase envelope around a key nobody else in the household has. A member's
  first passphrase envelope must name the household's recovery envelope; otherwise the server
  answers `409 client_outdated` and stores nothing, and the current app asks you to reload.
- Vault: a household's second member can no longer destroy the first member's vault. The
  household-wide recovery envelope is write-once on the server (`409 vault_already_set_up`), and
  a member without an envelope of their own now **joins** the existing vault with the household's
  recovery code and their own passphrase instead of being offered "set up" (ADR-0067 addendum).
- Uploads from the PWA (guide attachments, recipe photos) are sent as multipart; they went out as
  JSON and always failed with 422.
- The operator console's theme button named its mode with a raw message id.
- Calendar: an end before the start is reported at the end field instead of the generic error.
- Calendar and scheduling: a `from`/`to` query bound without a time-zone offset
  (`GET /v1/calendar/events?from=2026-07-01T00:00:00`, same for `/v1/scheduling/slots`) is
  rejected with `422 validation`; it failed with 500. The same for naive times in the calendar's
  request bodies that failed with 500: cancelling or moving an occurrence, and a create or PATCH
  that mixed a naive with an offset-carrying time.
- `create_operator` refuses an argument that is not an e-mail address.
- `make install` uses `npm ci`, which leaves `web/package-lock.json` untouched.
- Worker: taskiq worker children no longer die every five seconds on an idle queue (redis-py 8
  default `socket_timeout` against the blocking `BRPOP`).
- Passkeys: registration now requires a discoverable credential, matching the usernameless login.
- Caddy: the operator-console site block is plain HTTP on the host name in `OPS_HOST` (no
  automatic HTTPS behind the TLS-terminating proxy).
- Dev stack: removed the unused MinIO service (its `latest` image is gone from Docker Hub) and
  the unused `CUSTODE_S3_*` settings; `backend/.dockerignore` keeps a host `.venv` out of the image.
- README: the quick start includes `make install`; new "Self-hosting" section (bring-up, proxy,
  first operator, running without SMTP, backup and restore).

### Known limitations

- Phase 11 (hardening and legal) is in progress; open items are tracked as issues once fixed.
- Android (phase 10) has not started; Google CalDAV is not supported.
