# Changelog

All notable changes to Custode. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The pre-release engineering
history (June–September 2026, German) is not part of the public repository.

## [Unreleased]

### Added

- Initial public release under AGPL-3.0: all modules of roadmap phases 0–9 (accounts and
  households, recipes and nutrition, meal planner, shopping list, calendars with CalDAV sync,
  tasks with points ledger and marketplace, vault, messaging, guides, notes, comments, wearables,
  weather, quick-capture), the operator console, GDPR export and erasure with purge jobs.
- Source-code link in the app footer (AGPL §13), English `README.md` and `docs/ARCHITECTURE.md`,
  contributor documentation, hardened CI, CodeQL, Dependabot.
- A lived-in demo household for `make seed-demo`.
- The English interface is reachable: the UI follows the browser language (German as fallback)
  and can be pinned per browser under Profile → Language.
- The account page shows admins the sign-in link for child accounts, with a copy button.

### Changed

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
