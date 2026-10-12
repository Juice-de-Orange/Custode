# Public demo

How to run a Custode demo that anyone on the internet may use: one shared household, a login shown
on the sign-in page, every hour back to a fresh seed. This is what `docker-compose.demo.yml` and
`CUSTODE_DEMO_MODE=on` are for. For a normal instance, read [operations.md](operations.md) instead.

The design rule: a visitor must neither reach anything outside the instance nor exhaust the host,
and whatever they write is gone within the hour.

## Run it

On the host, in the cloned repository:

```bash
# five database passwords, generated once (.env.demo is git-ignored)
for v in POSTGRES_PASSWORD APP_DB_PASSWORD MAINT_DB_PASSWORD OPS_DB_PASSWORD OPS_ACTIONS_DB_PASSWORD; do
  echo "$v=$(openssl rand -hex 24)"; done > .env.demo

docker compose -f docker-compose.demo.yml --env-file .env.demo up -d --build
```

The stack listens on `http://127.0.0.1:8090` only (`CUSTODE_DEMO_PORT` in `.env.demo` changes
the port). Point your tunnel at that address — for a Cloudflare Tunnel, an ingress rule
`service: http://127.0.0.1:8090` on the demo's host name. Put your imprint and privacy policy into
`legal/` as for any instance ([operations.md](operations.md#legal-pages)); a public demo is a
public service.

On first start the `demo-reset` container seeds the demo household (English; set
`CUSTODE_DEMO_LANG=de` in `.env.demo` for the German one) a few seconds after the database is
migrated. Sign in with the login the sign-in page shows: `admin@custode.local` /
`custode-admin-demo`. Three more members exist (Jonas, Lea with the same password, the child Noah).

## What the demo does differently

`CUSTODE_DEMO_MODE=on` (default off — off means none of the following exists):

- **Refused server-side** with `403` and the problem type
  [`demo_disabled`](errors.md#demo-mode), before the request
  reaches a module: sign-up, password reset, e-mail verification, invites, child accounts,
  membership changes, leaving or dissolving the household, the digest e-mail, TOTP, passkeys,
  profile, session revocation and deletion of the shared account, recipe photo and guide
  attachment uploads, calendar file import, recipe import from a URL, the ICS export feed, CalDAV
  subscriptions, the vault, Oura, weather lookups, feedback, the live-update stream (`/v1/stream`)
  and the operator console (`/ops`). The complete list is `BLOCKED` in `backend/app/demo.py`; a
  test checks that every entry matches a real route.
- **Every external adapter off**, whatever the environment says: no SMTP, no CalDAV, no Oura, no
  LLM, no GitHub, no Open-Meteo, no file storage. Even a path the list missed has no way out.
- **Limits:** 60 requests per 10 seconds per visitor (`429 demo_rate_limited` with
  `Retry-After`), request bodies up to 256 KiB (`413 demo_payload_too_large`; Caddy enforces the
  same cap for bodies without `Content-Length`), at most 64 concurrent requests in the api
  (uvicorn answers `503` beyond that). The visitor is identified by `CF-Connecting-IP`, which
  Cloudflare sets and overwrites; behind another tunnel set `CUSTODE_DEMO_CLIENT_IP_HEADER` to
  that tunnel's header, or empty to use the connection's address.
- **Search engines:** `X-Robots-Tag: noindex, nofollow` on every response, `robots.txt` disallows
  everything, and the page adds a `robots` meta tag.
- **The UI** shows a banner on every page ("Demo — data resets every hour. Do not enter personal
  data.", German too), fills in the shared login, explains instead of offering sign-up and
  password reset, hides the vault, and names the reason when the server refused an action.

## The hourly reset

`python -m app.scripts.demo_reset` (the `demo-reset` service runs it with `--loop`: at start and at
every full hour). The first run copies the freshly migrated, empty database — the migrations'
reference data included — into the schema `demo_base` and seeds the household. Every later run
restores that copy in one transaction and seeds again, so the meal plan is always this week's and
tasks are due today. A reset takes about 5 seconds; `/healthz` and `/readyz` stay green
throughout, and the banner says "resetting" to anyone who loads a page meanwhile. Visitors who
were signed in are signed out (the accounts are new) and sign in again with the prefilled login.

Run one by hand:

```bash
docker compose -f docker-compose.demo.yml --env-file .env.demo exec demo-reset \
    python -m app.scripts.demo_reset
```

The command refuses to run without `CUSTODE_DEMO_MODE=on` — it deletes every row.

## Isolation and resources

Its own Compose project (`custode-demo`) and networks. `postgres`, `redis`, `migrate`, `api`,
`worker`, `scheduler` and `demo-reset` share an **internal** network without a route to the
internet; only `web` (Caddy) also sits on an edge network and publishes the one port, on
`127.0.0.1`. `api`, `worker`, `scheduler` and `demo-reset` run with a read-only file system; every
container has `no-new-privileges`. Limits per service:

| Service | Memory | CPUs | Processes |
|---|---|---|---|
| postgres | 384 MiB | 1.0 | 200 |
| redis | 64 MiB (48 MiB data, only keys with a TTL are evicted) | 0.25 | 50 |
| api | 384 MiB | 1.0 | 100 |
| worker | 256 MiB | 0.5 | 100 |
| scheduler | 192 MiB | 0.25 | 50 |
| demo-reset | 256 MiB | 0.5 | 50 |
| web | 64 MiB | 0.5 | 50 |

Logs rotate at 3 × 10 MB per container. Nothing is persisted except the database volume.

## Update

The base copy belongs to one schema version. After pulling a version with new migrations, recreate
the demo — there is nothing in it worth keeping:

```bash
docker compose -f docker-compose.demo.yml --env-file .env.demo down -v
docker compose -f docker-compose.demo.yml --env-file .env.demo up -d --build
```

Without `down -v` the reset refuses ("the base copy is from revision …") and the logs say so.

## What remains a risk

- **Shared content.** All visitors use one household: whatever someone writes (a note, a task
  title, a link in Markdown) is visible to the next visitor until the reset. Text is capped by the
  body limit, not moderated.
- **Distributed floods.** The rate limit is per address; many addresses together are limited only
  by the concurrency cap and the container limits — the edge (Cloudflare) is the place for more.
- **The demo login is public.** Anyone can sign in as the demo admin; everything that would let
  them lock others out (password, second factor, passkeys, sessions, membership) is refused.
