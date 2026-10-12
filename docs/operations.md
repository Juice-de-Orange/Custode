# Operations

How to run your own Custode instance: install, configure, put a proxy in front, back up, restore
and update. This is the English summary of the operational parts of ADR-0020 (production
deployment) and ADR-0024 (Caddy front), both German, plus what an operator needs from
`docker-compose.prod.yml`, `.env.prod.example` and `infra/`. Every command below was run as
written on a fresh stack with data (the only change for that run: a Compose project name and
host ports of the test machine).

All commands run on the host, in the cloned repository, and use the production stack file. If you
add your own override file (for ports, say), add `-f your-override.yml` after
`-f docker-compose.prod.yml` in every command.

## What runs

| Service | Image | Role | State |
|---|---|---|---|
| `postgres` | `postgres:18` | database, row-level security | volume `pgdata` |
| `redis` | `redis:7-alpine` | job queue, sessions, short-lived tokens | volume `redisdata` (no backup needed) |
| `migrate` | `custode-api` | applies the database migrations on every `up`, then exits; the app services wait for it | — |
| `api` | `custode-api` | FastAPI, published on `127.0.0.1:8080` (health checks only; `CUSTODE_API_PORT` moves it) | volume `storagedata` (photos, attachments) |
| `worker` | `custode-api` | background jobs, outbox dispatcher | — |
| `scheduler` | `custode-api` | fires the cron jobs (the worker runs them) | — |
| `web` | `custode-web` (Caddy) | serves the PWA and proxies `/v1` to the api; plain HTTP on `:80`, no host port | your `legal/` folder, read-only |

The images are `ghcr.io/juice-de-orange/custode-api` and `ghcr.io/juice-de-orange/custode-web`
(linux/amd64 and linux/arm64), published by `.github/workflows/release.yml` for every release tag:
`<version>`, `<major>.<minor>` and `latest`. `CUSTODE_VERSION` in `.env` picks the tag (empty =
`latest`). Where an image cannot be pulled — before the first release, or offline — Compose builds
it from the checkout (`build:` stays in the file). Build the web image yourself if you set
`CUSTODE_SOURCE_URL`: the published one links the upstream repository.

The Compose project is called `custode` (`name:` in the file), so volumes are `custode_pgdata`,
`custode_storagedata`, … and the network is `custode_default`. Memory limits per service are set
in the file (about 2 GB in total). The stack expects a TLS-terminating reverse proxy or tunnel in
front of `web`; it publishes no database port.

## Install

Requirements: Docker with Compose v2.24 or newer, git.

```bash
git clone https://github.com/Juice-de-Orange/Custode.git
cd Custode
./setup                      # writes .env: every password and CUSTODE_CRYPTO_KEY generated
# edit .env, see "Configure": delete the COMPOSE_FILE line (the localhost quick start),
# set CUSTODE_PUBLIC_BASE_URL and OPS_HOST, and SMTP if you want mail
docker compose -f docker-compose.prod.yml up -d
```

`./setup` refuses to overwrite an existing `.env`. To fill the file by hand instead, copy
`.env.prod.example` to `.env`, put one `openssl rand -hex 24` value into each `*_PASSWORD` and
generate the key with
`docker compose -f docker-compose.prod.yml run --rm --no-deps api python -c "from app.kernel.crypto import generate_key; print(generate_key())"`.

The database roles (`custode_app`, `custode_maint`, `ops_readonly`, `ops_actions`) are created
from the `.env` passwords by `infra/postgres/init.prod.sh`, **only on the first start of an empty
`pgdata` volume**. Changing a `*_PASSWORD` in `.env` later does not change the role; use
`ALTER ROLE … PASSWORD …` in the database as well. Migrations always run before the app starts:
the `migrate` job runs `alembic upgrade head` on every `up` and the app services wait for it.

## Configure

`.env` holds every setting; `.env.prod.example` explains each one. What you have to set:

| Variable | What |
|---|---|
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `MAINT_DB_PASSWORD`, `OPS_DB_PASSWORD`, `OPS_ACTIONS_DB_PASSWORD` | one random value each (`openssl rand -hex 24`) |
| `CUSTODE_CRYPTO_KEY` | encrypts stored CalDAV passwords and wearable tokens. Generate it once (command above) and **keep it with your backups**: without the same key those credentials are unreadable and must be entered again. There is no rotation yet (issue #7). Empty = those features stay off. |
| `CUSTODE_PUBLIC_BASE_URL` | the public origin, e.g. `https://home.example.com` (links in e-mails, OAuth redirects) |
| `OPS_HOST` | host name of the operator console, e.g. `ops.example.com` |

Optional: `CUSTODE_SMTP_*` (mail; empty host = no mail, see below), `CUSTODE_OURA_*` (wearables),
`CUSTODE_GITHUB_TOKEN`/`CUSTODE_GITHUB_REPO` (forward in-app feedback as issues),
`CUSTODE_CALDAV_*`, `CUSTODE_OTLP_ENDPOINT` (tracing), `CUSTODE_GIT_SHA`/`CUSTODE_APP_VERSION`
(shown in the operator console), `CUSTODE_LEGAL_DIR` and `CUSTODE_SOURCE_URL` (see "Legal pages").

To change the api's loopback port (`127.0.0.1:8080`), use an override file instead of editing
the stack file, so `git pull` stays clean:

```yaml
# docker-compose.override-ports.yml
services:
  api:
    ports: !override ["127.0.0.1:8092:8000"]
```

`!override` needs Docker Compose 2.24 or newer; without it, Compose would add the port to the
existing one instead of replacing it.

**Without SMTP.** Leave `CUSTODE_SMTP_HOST` empty (the template ships a placeholder host — clear
it). Registration and login work, accounts stay "e-mail not verified" (nothing is gated on it),
and no mail is sent at all: no verification, no weekly digest, **no password reset** — a member
who forgets the password cannot reset it.

**Mail language.** Each mail (verification, password reset, weekly digest) is written in the
recipient's account language: German for a German locale, English for everything else. The web
app sets it at registration from the interface language and updates it when the person changes
the language on their profile page; accounts created through the API without a `locale` start in
German.

## Reverse proxy

`web` publishes no host port. Two ways to reach it:

1. **Proxy or tunnel container on the stack network.** Attach it to `custode_default` (the
   network is `<project>_default` if you run the stack under another project name) and point it
   at **`http://custode-web:80`**. `custode-web` is a network alias of the `web` service and does
   not depend on the project name. Do not use the bare service name `web`: a proxy attached to
   several Compose networks resolves `web` to whichever stack answers first. The container name
   (`custode-web-1`) works too, but changes with the project name.
2. **Loopback port.** Publish `web` on the host's loopback with an override file and proxy to it:

   ```yaml
   services:
     web:
       ports: ["127.0.0.1:8081:80"]
   ```

Either way: terminate TLS in the proxy, forward the original `Host` header unchanged, and route
both host names — the app's and `OPS_HOST` — to the same target. Caddy serves both as plain HTTP
and picks the site by `Host`. The api's own port (`127.0.0.1:8080`) bypasses Caddy; use it for
health checks: `/healthz` (process up) and `/readyz` (database and Redis reachable).

## First operator account

The operator console (on `OPS_HOST`) has no sign-up. Create the first operator on the host:

```bash
docker compose -f docker-compose.prod.yml run --rm api \
    python -m app.scripts.create_operator you@example.org
```

It prints a generated password and the TOTP secret **once** (TOTP is mandatory). A re-run for the
same address changes nothing. Members register in the app itself; the first one creates a
household.

## Legal pages

The footer links to an imprint (`/impressum`) and a privacy policy (`/datenschutz`). Their text
belongs to whoever runs the instance, so it is not in the code: put Markdown files into the
`legal/` folder of the checkout, and the `web` container serves them under `/legal/`.

| File | Page |
|---|---|
| `legal/imprint.md` | imprint |
| `legal/privacy.md` | privacy policy |
| `legal/imprint.de.md`, `legal/privacy.en.md`, … | the same page in that UI language (`de`, `en`); wins over the file without a language |

- Without a file the page says "The operator of this instance has not provided an imprint / a
  privacy policy yet" — it never shows placeholder text that looks like a real one.
- Changes show up on the next page load; no rebuild, no restart.
- The files are ignored by git, so `git pull` never touches them. To keep them elsewhere, set
  `CUSTODE_LEGAL_DIR=/path/to/folder` in `.env` and run `docker compose -f docker-compose.prod.yml up -d web`.
- Markdown subset: `#`/`##`/`###` headings, paragraphs (a single line break stays a line break —
  addresses), `-` lists, `**bold**`, `*italic*`, links to `https://`, `mailto:`, `tel:`. HTML in
  the file is shown as text.
- `legal/privacy.example.md` is a starting point that lists what Custode itself processes.

**For operators in the EU.** This is orientation, not legal advice. If you offer the instance to
people outside your own household, you are the controller under the GDPR and need a privacy notice
(Art. 13 GDPR): who you are, what is processed and why, the legal bases, retention, processors
(hosting provider, mail provider), and the data subjects' rights. Depending on your country and on
how public the service is, an imprint may be required as well (in Germany § 5 DDG, in Austria § 5
ECG and § 25 MedienG). Check which optional modules you enable — wearables process health data
(Art. 9 GDPR, consent-based), weather and LLM quick-capture call external services. The in-app
GDPR functions (export, account deletion, household dissolution) are described in
`docs/LOESCHKONZEPT.md` (German).

**Source code link (AGPL-3.0 §13).** The footer's "Source code" link points at this repository.
If you run a modified version for others, it must point at your version's source: set
`CUSTODE_SOURCE_URL=https://…` in `.env` and rebuild the web image
(`docker compose -f docker-compose.prod.yml build web` then `up -d web`).

## Backup

State lives in two volumes: `pgdata` (everything except files) and `storagedata` (recipe photos,
guide attachments). Back up both, plus `.env` — above all `CUSTODE_CRYPTO_KEY` — and your `legal/`
folder. `redisdata` holds only the job queue and short-lived state (access tokens, WebAuthn
challenges, each session's active household) and needs no backup.

```bash
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U custode -Fc custode > custode.dump
docker compose -f docker-compose.prod.yml run --rm --no-deps -T api tar czf - -C /data/storage . > storage.tgz
```

Both run while the stack is up. Copy the two files and `.env` off the host.

## Restore

Into empty volumes — a new host, or after `docker compose -f docker-compose.prod.yml down -v` —
with the saved `.env` in place:

```bash
docker compose -f docker-compose.prod.yml up -d --wait postgres redis   # first init creates the roles
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U custode -d custode < custode.dump
docker compose -f docker-compose.prod.yml run --rm --no-deps -T api tar xzf - -C /data/storage < storage.tgz
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

The dump carries no roles; they come from the init script, which is why postgres starts on an
empty volume first. Members who were signed in during the restore land on "No active household"
("Kein Haushalt aktiv") until they pick the household on the account page or sign in again —
nothing is lost, the state lived in Redis.

## Update

From one version to the next (a release tag or `main`). The database migrations are forward-only:
**take a backup first** — restoring it is the way back.

```bash
# 1. let the job queue run empty: stop the scheduler, wait until the worker has taken every job
docker compose -f docker-compose.prod.yml stop scheduler
docker compose -f docker-compose.prod.yml exec -T redis redis-cli LLEN taskiq   # repeat until 0

# 2. backup (see "Backup")

# 3. new code, new images, migrations, restart
git pull                      # or: git fetch --tags && git checkout v0.2.0
docker compose -f docker-compose.prod.yml pull    # released images (CUSTODE_VERSION) — or `build` from source
docker compose -f docker-compose.prod.yml up -d   # `migrate` applies the new migrations first
```

Why the queue first: the Redis list `taskiq` holds jobs the scheduler fired but the worker has not
run yet, serialised by the old code. Jobs are cron runs that come again on their next tick, so a
non-empty queue is not lost data — but a new version should not have to parse an old version's
messages. Domain events wait in the database outbox, not in Redis, and survive any restart.
`up -d` at the end starts the scheduler again.

`docker compose -f docker-compose.prod.yml logs migrate` shows the migrations it applied; when
there were none it prints only the context lines. Check the result with `docker compose -f docker-compose.prod.yml ps` (all services
`Up`, api/worker/scheduler `healthy`) and `curl -fsS http://127.0.0.1:8080/readyz`.

Read `CHANGELOG.md` before you update; settings that changed are listed there. New settings
appear in `.env.prod.example`, not in your `.env`: compare the two after `git pull`
(`diff <(grep -o '^[A-Z_]*=' .env.prod.example | sort) <(grep -o '^[A-Z_]*=' .env | sort)`)
and copy over what you want to set — a variable missing from `.env` takes its default.

## Logs and health

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api worker
curl -fsS http://127.0.0.1:8080/readyz
```

Logs are JSON (`CUSTODE_LOG_JSON=true`). Every API error response carries a `reference` code;
for an unexpected server error (5xx) the api logs the full traceback under the same reference, so
a support request can be matched to the log line. The error codes are listed in
`docs/errors.md`.

## Known limits

- No rotation path for `CUSTODE_CRYPTO_KEY` (issue #7).
- The database roles are created only on the first init of `pgdata`; a stack that was first started
  without the `OPS_*` passwords has no operator roles, and the console then falls back to the app
  role (the operator boundary holds only in the application, not in the database).
- Not exercised by the maintainers: real SMTP delivery, Oura, quick-capture with an LLM, hardware
  authenticators, operation behind a real TLS-terminating proxy (README, "What has been checked").
