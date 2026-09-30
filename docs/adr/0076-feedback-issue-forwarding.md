# ADR-0076 — Feedback → Issue-Tracker: Best-Effort-Weiterleitung als Graceful Enhancement (Null-Adapter)

**Status:** beschlossen · **Phase:** 8 (P8-S5-Folge) · **Datum:** 2026-07-05
**Kontext-KONZEPT:** §5.12 (Feedback-Kanal), `ENTWICKLUNGSKONZEPT` P5 (Graceful Enhancement) & E2
(Modulgrenzen: Ports/Adapter), `ARCHITECTURE` §8.2 (transaktionaler Outbox) + §8.4 (Worker),
ADR-0039 (Modul-Outbox-Handler am Composition-Root), ADR-0027/0070 (Mail-Factory/Null-Adapter-Muster).
Roadmap Phase 8 („Feedback-Kanal … Verbleibend: Issues-Weiterleitung").

## Kontext
Das In-App-Feedback (`feedback`) landet in der Fachtabelle und in der Betreiber-Inbox (View
`ops_feedback`). Für die F&F-Beta will der Betreiber eine Einsendung optional in seinen **Issue-Tracker**
übernehmen, um sie dort zu triagieren. Drei Spannungen: (a) **Modulgrenzen** — `feedback` importiert nur
`kernel/*`, `modules`/`kernel` dürfen keine `adapters` importieren (import-linter); (b) **kein Pflicht-
Infra / kein Secret im Repo** — die Weiterleitung darf die App nicht voraussetzen und kein Token
mitliefern; (c) **Ziel-Tracker**: die Roadmap nannte GitLab, das Repo liegt aber auf **GitHub**.

## Entscheidung

### Port + Null- + GitHub-Adapter, Auswahl am Composition-Root
Neuer Kernel-Port `kernel/ports/issues.py::IssueTrackerPort` (`async forward(title, body, labels) -> bool`).
Zwei Adapter: `adapters/null.NullIssueTracker` (No-Op, akzeptiert, kein Aufruf) und
`adapters/github/issues.GitHubIssueTracker` (POST `…/repos/{owner}/{repo}/issues`). Die Auswahl trifft die
**Factory** `app/issue_factory.build_issue_tracker(settings)` — GitHub nur, wenn **Token UND Repo** gesetzt
sind, sonst Null. Damit importiert weder `feedback` noch der Kernel je einen Adapter (das Muster von
`mail_factory`/ADR-0027).

### INERT per Default (Graceful Enhancement, P5)
`github_token`/`github_repo` sind `None`-Defaults in `settings.py` (Secrets via env
`CUSTODE_GITHUB_TOKEN`/`CUSTODE_GITHUB_REPO`, **nie im Repo**). Ohne Konfiguration greift der
Null-Adapter → **kein ausgehender Aufruf**, die App (Feedback + Betreiber-Inbox) funktioniert voll. Der
Merge dieses Slices verändert das Live-Verhalten also nicht.

### Auslöser: Outbox-Handler am Worker-Composition-Root (ADR-0039)
`feedback.created` wird bereits transaktional emittiert. Der Payload wird um die **Feedback-ID** ergänzt
(erst `flush` für die server-seitige `uuidv7`, dann `emit`), **kein Inhalt im Payload** (kein PII über die
ID hinaus). Der Handler `modules/feedback/handlers.on_feedback_created` öffnet eine eigene
**haushaltsgescopte** Session (RLS via `scoped_session`, nil-User), liest die Zeile über den **eigenen**
`feedback.service` und übergibt sie der reinen Abbildung `forward.build_issue` → `IssueTrackerPort`.
Registriert wird er in `app/worker.py` mit dem per Factory gewählten Tracker (Kernel importiert keine
Module — ADR-0039).

### Best-Effort + Privacy (P1)
Die Weiterleitung ist **best-effort**: sie darf die Einsendung nie brechen. Der Adapter fängt
`httpx.HTTPError` und degradiert zu `False`; der Handler kapselt zusätzlich und **loggt nur die
Fehlerklasse**, nie Titel/Body (`message` = Nutzerinhalt, kein PII in Logs). Zustellung ist
at-least-once → eine Re-Zustellung kann ein Duplikat-Issue öffnen (für Triage akzeptabel). Der
Feedback-Inhalt verlässt den Verbund nur in das **vom Betreiber konfigurierte, private** Repo — bewusste,
gescopte Betreiber-Entscheidung, per Default aus.

## Konsequenzen
- **Plus:** Saubere Grenzen (Port im Kernel, Adapter am Root, kein Modul→Adapter-Import; import-linter
  unverändert 24/0). Voll graceful — ohne Token passiert nichts, kein Pflicht-Infra, kein Secret im Repo.
- **Plus:** Keine neue Route/Tabelle/Migration → **kein OpenAPI-Drift, kein RLS-Neuland**. Kernlogik
  (Null/Real-Adapter, Mapping, Swallow) ohne Docker unit-getestet (`tests/test_feedback_forward.py`).
- **Minus:** Keine Deduplizierung → at-least-once kann Duplikat-Issues erzeugen (bewusst; Triage-Kontext).
- **Minus:** Nur GitHub-Adapter in v1; ein GitLab-Adapter wäre ein zweiter `IssueTrackerPort`-Impl
  hinter derselben Factory (Port bleibt stabil).
- **Offen:** Idempotenz-Marker gegen Duplikate, Label-/Assignee-Feinsteuerung, Rückverweis der
  Issue-URL in die Betreiber-Inbox.

## Alternativen
- **GitLab (Roadmap-Wortlaut):** verworfen zugunsten von **GitHub** (Repo-Heimat Juice-de-Orange/Custode);
  der Port ist tracker-neutral, ein GitLab-Adapter kann jederzeit ergänzt werden.
- **Direkter POST im Request-Pfad (Router/Service):** koppelt Nutzer-Latenz + Ausfall des Trackers an die
  Einsendung; verworfen — der Outbox-Handler entkoppelt (Einsendung persistiert immer).
- **`kernel/fetch.safe_fetch`:** ist der GET-only SSRF-Guard für **nutzer**gelieferte URLs (Rezept-Import);
  `api.github.com` ist ein fester, vertrauter Host aus Server-Config → schlichter `httpx`-Client (wie
  Ollama/Open-Meteo), kein SSRF-Neuland.
