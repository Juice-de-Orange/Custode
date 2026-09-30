# ADR-0017: `npm` als Web-Paketmanager

- **Status:** beschlossen
- **Datum:** 2026-06-14
- **Betrifft:** `web/` · **Bezug:** ENTWICKLUNGSKONZEPT E5/E8

## Kontext

Das Web-Frontend (React 19 + Vite) braucht einen Paketmanager mit Lockfile. Es
gibt (vorerst) nur ein Frontend-Paket — kein Monorepo-Workspace-Bedarf. Leitlinie:
die langweiligste Lösung, die reicht (E5/E8), keine Tool-Vielfalt ohne Not.

## Entscheidung

Wir nutzen **npm** (kommt mit Node LTS). `package-lock.json` wird committed. CI
installiert via `npm ci`.

## Konsequenzen

- **Positiv:** null Zusatzinstallation; Standard, stabil, überall dokumentiert;
  `npm ci` ist reproduzierbar und CI-tauglich.
- **Negativ / Kosten:** langsamer/größer als pnpm bei vielen Paketen — bei einem
  einzelnen Web-Paket irrelevant.
- **Revision-Auslöser:** echte Monorepo-Workspaces oder messbare Install-/Disk-Probleme
  → dann pnpm-Umstieg per neuem ADR.

## Alternativen (verworfen)

- **pnpm** — effizienter bei Workspaces/Disk; lohnt erst bei mehreren JS-Paketen.
- **yarn / bun** — zusätzlicher Tool-Zoo bzw. (bun) noch nicht „boring" genug.
