# ADR-0018: Monorepo-Layout und Doku-Kanonik

- **Status:** beschlossen
- **Datum:** 2026-06-14
- **Betrifft:** gesamtes Repo · **Bezug:** KONFIG/README.md, Roadmap Phase 0, KONZEPT §10

## Kontext

Roadmap Phase 0 nennt das Monorepo `/backend /web /infra /docs /KONFIG` und
zugleich eine „`docs/`-Struktur: ARCHITECTURE.md, MODULES/, adr/ …". `KONFIG/README.md`
verortet die Konzept-Dokumente (inklusive `ARCHITECTURE.md`) jedoch eindeutig in
`KONFIG/`. Daraus entstünde sonst eine doppelte `ARCHITECTURE.md` mit Drift-Risiko
(verstößt gegen E6/E9).

## Entscheidung

1. **Monorepo-Layout:** `/backend`, `/web`, `/infra`, `/docs`, `/KONFIG`;
   `CLAUDE.md`, `Makefile`, `docker-compose.dev.yml` in der Wurzel.
2. **`KONFIG/` ist kanonisch** für die Konzept-Dokumente. `ARCHITECTURE.md` bleibt
   **ausschließlich** `KONFIG/ARCHITECTURE.md`; dort wächst auch das Datenmodell/ER
   (KONZEPT §10). Es gibt **keine** zweite `docs/ARCHITECTURE.md`.
3. **`docs/`** enthält die lebende Engineering-Doku (adr/, MODULES/, templates/,
   BUGLOG, patterns, errors, NOTIFICATIONS, CHANGELOG). Die Roadmap-Formulierung
   „docs/ARCHITECTURE.md" wird durch einen Pointer in `docs/README.md` erfüllt.
4. **ADR-Register 001–015** bleibt im Abschnitt `KONFIG/ARCHITECTURE.md §17`
   (Single Source); neue ADRs ab 016 sind Einzeldateien in `docs/adr/`.

## Konsequenzen

- **Positiv:** kein Doppel-Dokument, kein Drift; klare Trennung „eingefrorenes
  Konzept" (KONFIG) vs. „mitwachsende Doku" (docs).
- **Negativ:** geringfügige Abweichung vom Wortlaut der Roadmap-Checkliste — bewusst
  und hier dokumentiert (E9: Konzept/ADR vor Code).

## Alternativen (verworfen)

- **`ARCHITECTURE.md` nach `docs/` verschieben** — widerspricht `KONFIG/README.md`
  und der Lese-Reihenfolge; KONFIG ist der eingefrorene Konzept-Kanon.
- **In beiden Orten pflegen** — garantierter Drift, verboten (E6).

**Nachtrag P9 (2026-07-30):** Für die Statuszeile eines ADR gilt ausschließlich das Vokabular aus
[`0000-template.md`](0000-template.md): *vorgeschlagen · beschlossen · revidiert · abgelöst durch
ADR-XXXX*. „akzeptiert" war über 36 Dateien eingerissen und ist eingesammelt — zwei Wörter für
denselben Zustand sind genau der Drift, den dieser ADR verhindern soll.
