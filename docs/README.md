# docs/ — lebende Engineering-Doku

Diese Mappe ergänzt die **Quelle der Wahrheit** in [`../KONFIG/`](../KONFIG/).
Aufgabenteilung (ADR-0018):

- **`KONFIG/`** — eingefrorene Konzept-Dokumente (Konzept, Architektur,
  Entwicklungskonzept, Roadmap, UX, Wettbewerb). Änderungen nur über
  Konzept-PRs/ADRs (Prinzip E9). Die technische Detailwahrheit steht in
  [`../KONFIG/ARCHITECTURE.md`](../KONFIG/ARCHITECTURE.md) — **dort**, nicht hier,
  wächst auch das ER-/Datenmodell (KONZEPT §10).
- **`docs/`** — Doku, die mit dem Code mitwächst:
  - [`adr/`](adr/) — Architecture Decision Records (Vorlage + Index).
  - [`MODULES/`](MODULES/) — ein Dokument je Fachmodul (Mensch **und** KI).
  - [`templates/`](templates/) — Vorlagen für Modul-`CLAUDE.md` und MODULES-Doku.
  - [`BUGLOG.md`](BUGLOG.md) — Bug-Historie (E10: Symptom → Ursache → Fix → Test → Lehre).
  - [`MANUAL_TESTS.md`](MANUAL_TESTS.md) — **Protokolle** für das, was die Gates strukturell
    nicht abdecken können (echte Geräte/Fremdserver/Zeitablauf). Alles andere gehört in einen Test.
    Die **Verpflichtungen** des Betreibers (Zugangsdaten, fremde Konten, Prüfungen am echten
    System) führt der Betreiber in einer eigenen Checkliste außerhalb dieses Repos.
  - [`LOESCHKONZEPT.md`](LOESCHKONZEPT.md) — **beide** Art.-17-Wege (Kontolöschung und
    Haushaltsauflösung) mit Fristen, Cron-Zeiten und den erzwingenden Gates.
  - [`patterns.md`](patterns.md) — Pattern-Katalog (E7).
  - [`errors.md`](errors.md) — Fehler-Referenzkatalog (RFC 9457).
  - [`NOTIFICATIONS.md`](NOTIFICATIONS.md) — Default-Matrix Benachrichtigungen (Phase 1).
  - [`../CHANGELOG.md`](../CHANGELOG.md) — Änderungshistorie (Keep a Changelog), im Repo-Root.

Regel: Jede Code-Einheit aktualisiert die zugehörige `docs/`-Datei im selben
Commit (ENTWICKLUNGSKONZEPT Teil C/D).
