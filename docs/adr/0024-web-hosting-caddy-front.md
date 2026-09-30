# ADR-0024: Web-Auslieferung via Caddy-Front (eine Origin)

- **Status:** beschlossen
- **Datum:** 2026-06-17
- **Betrifft:** CD, Betrieb, `web` · **Bezug:** ADR-0020 (Produktions-Deployment), ARCHITECTURE §14 („web Static via Caddy"), KONZEPT §8 (Cookies SameSite=Lax)

## Kontext

Die Auth-UI (PR #5) ist CI-grün, aber auf dem Produktionsserver gab es **kein Web-Hosting**: das gehärtete
Compose hatte nur `api`/`worker`, die Live-Domain lieferte unter `/` ein 404 vom API. Die
Session-Cookies sind **SameSite=Lax** → Web und API müssen **same-origin** laufen. ARCHITECTURE
sieht „web Static via Caddy" vor; `web/Dockerfile` (node baut `dist` → `caddy:2-alpine`) und
`infra/caddy/Caddyfile` (Reverse-Proxy) waren bereits scaffolded (vorgesehen ab Phase 8).

## Entscheidung

Ein **Caddy-`web`-Container** wird die Front: er serviert das gebaute SPA und **reverse-proxyt
`/v1`, `/healthz`, `/readyz`, `/metrics` → `api:8000`**; alles andere → SPA
(`try_files … /index.html`). **Eine Origin** → Cookies/CSRF funktionieren unverändert. Caddy
serviert **plain HTTP auf `:80`** (TLS terminiert der Reverse-Proxy/Tunnel upstream). Der Deploy-Job
startet `web` mit; der `api` bleibt unverändert (intern + `127.0.0.1:8080`). Die scaffoldete
Lösung wird von Phase 8 auf **Phase 1** vorgezogen.

**Betreiber-Schritt (Isolationsgrenze, ADR-0020):** Der Public-Hostname des Reverse-Proxys/Tunnels
zeigt aktuell auf den `api`-Container; er muss auf den **`web`-Container (`:80`)** umgestellt
werden (Proxy-Konfiguration des Betreibers außerhalb dieses Repos — ändert **nur der Betreiber**,
nie der Deploy-Automatismus). Bis dahin liefert die Domain weiter API-only aus (**kein Breakage**).

## Konsequenzen

- **Positiv:** same-origin SPA+API ohne CORS/`SameSite=None`; ARCHITECTURE-konform; repo-seitig
  automatisiert; `api` unverändert (kein Risiko für das laufende Backend).
- **Negativ / Kosten:** ein zusätzlicher Container (96 M RAM) + ein einmaliger, manueller
  Tunnel-Repoint durch den Betreiber; der web-Image-Build braucht beim Deploy Node (`npm ci`/
  `build`) auf dem Produktionsserver.
- **Auswirkungen:** `docker-compose.prod.yml` (web-Service), `ci.yml` (Deploy `up … web`),
  `infra/caddy/Caddyfile` auf `:80`. **Kein** Backend-/API-Change.

## Alternativen (verworfen)

- **FastAPI serviert die SPA** — kein Tunnel-Repoint nötig, aber weicht von ARCHITECTURE ab
  und koppelt das Web ins `api`-Image (Node im api-Build). Verworfen zugunsten der dokumentierten,
  sauberen Trennung.
- **Separates Static-Hosting (z. B. Cloudflare Pages) für `/`** — andere Origin → CORS +
  `SameSite=None`-Cookies nötig, bricht das same-origin-Cookie-Modell. Verworfen.
