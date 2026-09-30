# Custode — Konzept- & Startpaket

Dies ist die vollständige, entwicklungsbereite Grundlage für **Custode**
(Arbeitsname; technischer Projektname `custode`, Marketingname später leicht
änderbar). Konzept-Stand: **v1.0 final, 10.06.2026** — nach zwei Audits und
Best-Practice-Recherche. Die Audit-Kennungen (A-xx/B-xx/C-xx) in den Dokumenten verweisen
auf das interne Konzept-Audit vom Juni 2026 (nicht im Repo).

## So legst du es im Repo ab
```
custode/
├─ CLAUDE.md                ← Arbeitsanweisung für Claude Code (Repo-Wurzel!)
└─ KONFIG/                  ← dieser Ordner
   ├─ KONZEPT.md            ← WAS & WARUM (Quelle der Wahrheit)
   ├─ ARCHITECTURE.md       ← WIE technisch (C4, API, Sync, RLS, Obs., ADRs)
   ├─ ENTWICKLUNGSKONZEPT.md← WIE wir arbeiten (Prinzipien, DoD, Tests, Design)
   ├─ Roadmap_to_V0.1.md    ← Bau-Reihenfolge & Checklisten (Phase 0–12)
   ├─ UX_KONZEPT.md         ← Navigation, Screens, 5 Kern-Flows
   └─ WETTBEWERB.md         ← Feature-Herkunft (T-Nummern)
```
`CLAUDE.md` gehört in die **Repo-Wurzel**, die übrigen Dateien in `KONFIG/`.
Die Pfade in `CLAUDE.md` zeigen bereits auf `KONFIG/`.

## Lese-Reihenfolge für den Einstieg
1. CLAUDE.md (Regeln, Stack, Tabus)
2. KONZEPT.md (Module 5.1–5.19, Datenmodell, §11 Betreiber-Konsole)
3. ARCHITECTURE.md (Modulgrenzen, Sync §10, RLS §9, Observability §12)
4. ENTWICKLUNGSKONZEPT.md (Definition of Done, Design „Ruhige Moderne")
5. Roadmap_to_V0.1.md → Start bei Phase 0

## Status & einziger offener Punkt
- Alle inhaltlichen Entscheidungen getroffen (17.1–17.8 final).
- Markenname **Custode** ist Arbeitsname; bewusst NICHT blockierend — Code
  nutzt `custode` technisch und `BRAND_NAME` für Anzeige. Markencheck später.
- Entwicklung startet bei **Phase 0** (Roadmap).

## Was als Nächstes entsteht (in Phase 0, mit Claude Code)
Repo-Skelett, CI-Pipeline, Backend-/Web-Gerüst, `docs/`-Struktur (ADRs, BUGLOG,
patterns, errors), `docker-compose.dev.yml`, `make`-Targets. Done-Kriterien
stehen in der Roadmap.
