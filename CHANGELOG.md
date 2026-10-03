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

### Changed

- Production deployment files are generic templates (`docker-compose.prod.yml`,
  `.env.prod.example`, `infra/postgres/init.prod.sh`, `infra/caddy/Caddyfile`); the deploy job
  is not part of the public CI.
- Problem-type URIs point at the error catalogue in this repository.

### Fixed

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
