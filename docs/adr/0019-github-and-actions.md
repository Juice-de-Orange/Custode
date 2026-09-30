# ADR-0019: GitHub + GitHub Actions statt GitLab CE; Deploy auf den Produktionsserver

- **Status:** beschlossen
- **Datum:** 2026-06-14
- **Betrifft:** CI/CD, Repo-Hosting · **Bezug:** ARCHITECTURE §14 (CI/CD), KONZEPT §11 (Betrieb)

## Kontext

Das Konzept nannte **GitLab CE** als vorhandene Infrastruktur (ARCHITECTURE §14:
„CI/CD über vorhandenes GitLab CE … Deploy-Job zieht auf den Produktionsserver"). Der Betreiber
wechselt auf **GitHub** (privates Repo) und will bei jedem grünen Push **direkt auf
den Produktionsserver** deployen, damit alles in der realen Linux-/Docker-Umgebung läuft.

## Entscheidung

1. **Repo:** privat auf GitHub (Closed Source — niemals public).
2. **CI:** GitHub Actions (`.github/workflows/ci.yml`) mit **denselben Gates** wie
   zuvor (ruff, ruff format, mypy --strict, import-linter, pytest inkl.
   Testcontainers-RLS-Test, eslint, tsc, vitest, Web-Build, OpenAPI-Regen-Diff,
   gitleaks, trivy). `.gitlab-ci.yml` entfällt (in der Git-Historie erhalten).
3. **CD:** Actions-Job `deploy` → SSH auf den Produktionsserver → `git pull` + `docker compose`
   + `alembic upgrade head`. Gated über `vars.DEPLOY_ENABLED == 'true'` und Secrets
   (`DEPLOY_HOST/USER/SSH_KEY/PORT/PATH`) — bleibt inaktiv, bis konfiguriert. Der Job lebt
   **im privaten Betreiber-Repo, nicht im öffentlichen** Workflow (s. Nachtrag unten).
4. **Provider-Neutralität:** Die Gates selbst sind unverändert und provider-
   agnostisch; ARCHITECTURE §14 nennt GitLab — der Provider ist über diesen ADR
   ausgetauscht, das Gate-Set bleibt verbindlich.

## Konsequenzen

- **Positiv:** Actions-Runner (ubuntu-latest) haben Docker → der **RLS-Negativtest
  und künftige Integrationstests laufen in CI** (echte Verifikation ohne lokales
  Docker/WSL2). Deploy auf den Produktionsserver erfüllt das Phase-0-🎯 „CI deployt leeres
  Gerüst auf Staging".
- **Negativ / Kosten:** Secrets-Verwaltung in GitHub (nie im Repo, gitleaks-Gate);
  der Server braucht einen Deploy-Key (Lesezugriff aufs private Repo) + Docker.
- **Sicherheit:** Der Deploy nutzt vorerst `docker-compose.dev.yml` (Dev-Defaults).
  Vor echten Nutzerdaten: gehärtetes Staging/Prod-Compose mit echten Secrets
  (Phase 8/12, KONZEPT §11).

## Nachtrag 2026-08-01: die Schleife wird ernst genommen

Ab Phase 11 mergt und deployt der Entwicklungsablauf **in Serie** — mehrere PRs am Tag, jeder mit
automatischem Deploy. Eine Bestandsaufnahme der Datei hat vier Dinge gezeigt, die bei einzelnen
PRs folgenlos blieben und bei Serien nicht mehr:

1. **`security` war keine Deploy-Bedingung.** `needs: [backend, web, contract]` — ein roter
   gitleaks oder trivy hat den Deploy nie aufgehalten, obwohl CLAUDE.md beide als blockierende
   Gates führt. Ein geleaktes Secret wäre auf den Produktionsserver durchgereicht worden. **Jetzt
   `needs: [backend, web, contract, security]`.**
2. **Der Deploy brach sich selbst ab.** `cancel-in-progress: true` auf der Gruppe
   `deploy-prod`: zwei Merges kurz hintereinander konnten den ersten Lauf **zwischen**
   `alembic upgrade head` und `docker compose up -d` beenden — migriertes Schema, alte API. Das
   ist genau der Zustand, den die expand/contract-Reihenfolge im Skript vermeiden soll. **Jetzt
   `false`:** Deploys reihen sich, und weil das Skript `git reset --hard origin/main` macht, holt
   der zweite Lauf ohnehin den neuesten Stand. Doppelt deployen ist billig, halb deployen nicht.
3. **Kein Job hatte `timeout-minutes`** — es galt GitHubs Default von 360 Minuten. Ein hängender
   Testcontainer hätte sechs Stunden Runner-Zeit verbrannt, bevor irgendetwas rot wird. Grenzen
   jetzt bei grob dem Zwei- bis Dreifachen der realen Laufzeit (backend 20, web 12, contract 10,
   security 10, deploy 15; real ~7,5 min Wanduhr, vom Backend-`pytest` bestimmt).
4. **`oasdiff` lief überhaupt nicht.** CLAUDE.md und ENTWICKLUNGSKONZEPT führen „oasdiff ohne
   Breaking" seit jeher als blockierendes Gate bzw. DoD-Punkt; gebaut war nur der
   Regen-Drift-Check (`git diff --exit-code`), der eine *unregenerierte* Datei findet, aber keine
   *kaputt gemachte* API. Ein entfernter Endpunkt oder ein neu verpflichtendes Request-Feld wäre
   unbemerkt durchgegangen. **Jetzt läuft `oasdiff breaking --fail-on ERR`** im `contract`-Job,
   gegen `backend/openapi.json` des Zielbranches, gepinnt auf v1.27.0 als Release-Binary (statt
   der Action — eine Indirektion weniger, und der Fehlerfall gehört uns). Nur auf Pull Requests:
   auf `main` gibt es keinen sinnvollen Vergleichspunkt mehr.

Dazu eine Sparmaßnahme ohne Sicherheitsbezug: **Workflow-Concurrency je `github.ref`** bricht
überholte Läufe ab — **außer auf `main`**, wo der Deploy daran hängt.

**Was bewusst offen bleibt:** Branch Protection ist auf einem privaten Repo im Free-Plan nicht
verfügbar (`gh api …/protection` → 403). Grüne CI ist damit keine technische Merge-Bedingung,
sondern Disziplin. Der Deploy ist die eigentliche Sperre — er läuft nur bei vier grünen Jobs.

## Alternativen (verworfen)

- **GitLab CE behalten** — Betreiber-Präferenz GitHub.
- **GitHub public** — verstößt gegen „Closed Source" (KONZEPT §0).
- **Self-hosted Actions-Runner auf dem Produktionsserver** — möglich, aber SSH-Deploy ist
  einfacher und hält den Server schlank; bei Bedarf später umstellbar (neuer ADR).

## Nachtrag 2026-09: öffentliches Repo, privater Deploy

Das Repo ist inzwischen **öffentlich** (AGPL-3.0). Der öffentliche Workflow enthält nur die
Gates; der `deploy`-Job samt Secrets und Zielsystem lebt **im privaten Betreiber-Repo**. Punkt 1
der Entscheidung („niemals public") ist damit überholt; das Gate-Set bleibt unverändert.
