# CLAUDE.md — Projekt **Custode**

> **For English readers.** Custode is a self-hostable household platform — recipes, meal
> planning, shopping list, calendar, chores with a points ledger, notes, guides and more —
> built as a FastAPI modular monolith (`backend/`) with a React 19 PWA (`web/`). This file is
> the binding working instruction for every session in this repo, AI-assisted or human: module
> boundaries, tenant isolation, ledger invariants, definition of done and CI gates are not
> negotiable. The concept documents in `KONFIG/` and `docs/` are written in German by design
> (they are the project's source of truth); code, comments and commit subjects are English,
> and the UI ships in German and English. Licence: AGPL-3.0 (see `LICENSE`).

> Diese Datei ist die oberste Arbeitsanweisung für Claude Code in diesem Repo.
> Sie hat Vorrang vor Gewohnheiten und Default-Verhalten. Bei Konflikt gilt:
> **Sicherheit > KONZEPT/ADR > diese Datei > Bequemlichkeit.**

## Was Custode ist
Eine kommerzielle Haushaltsplattform (WebApp zuerst, dann Android). Module:
Rezepte, Mealplanner, Einkaufsliste, Kalender, Haushaltsaufgaben mit
Punkte-Ökonomie & Marketplace, Vault, Messaging, Anleitungen, Notizen,
Finanzen, Wearables, Wetter, KI-Zuruf. Ziel: durchdachter und ruhiger als jede
Alternative.

**„Custode" ist Arbeits-/Marketingname und kann sich ändern.** Der technische
Projektname ist überall `custode` (Repo, Python-Package, DB-Name, Bucket).
Marketingname nur über die i18n-Konstante `BRAND_NAME` ausgeben — **nie**
hartcodieren. Ein Namenswechsel darf später ausschließlich Anzeigetexte
betreffen.

## Quellen der Wahrheit (immer zuerst lesen)
1. `KONFIG/KONZEPT.md` — WAS & WARUM (Module, Regeln, Datenmodell, Roadmap).
2. `KONFIG/ARCHITECTURE.md` — WIE technisch (C4, API, Sync, RLS, ADRs, Obs.).
3. `KONFIG/ENTWICKLUNGSKONZEPT.md` — WIE wir arbeiten (Prinzipien, DoD, Tests).
4. `KONFIG/Roadmap_to_V0.1.md` — Reihenfolge & Checklisten je Phase.
5. `KONFIG/UX_KONZEPT.md` — Navigation, Screens, Kern-Flows.
6. `KONFIG/WETTBEWERB.md` — Feature-Herkunft (T-Nummern).

Bei jeder Aufgabe zuerst klären, welche KONZEPT-Abschnitte betroffen sind.
Weicht die Realität vom Konzept ab → **erst Konzept/ADR ändern, dann Code**
(Prinzip E9). Niemals still vom Konzept abweichen.

## Harte Regeln (nicht verhandelbar)
- **Modulgrenzen:** `modules/*` importieren nur `kernel/*`, niemals einander.
  Quermodul-Kommunikation nur über Domain-Events oder exportierte
  Service-Interfaces (`modules/<x>/api.py`). Kein Modul liest fremde Tabellen.
  (import-linter erzwingt das in CI.)
- **Mandanten-Isolation:** jede Fachzeile hat `household_id`; RLS aktiv mit
  `FORCE ROW LEVEL SECURITY`; App-DB-Rolle ohne BYPASSRLS/Ownership. Jede neue
  Tabelle braucht einen Negativtest **gegen jede Grenze, die ihre Policy zieht** —
  Haushalt, und wo `member_id` im Prädikat steht (Art.-9-Tabellen, ADR-0081) auch
  Mitglied — **plus die Gegenprobe, dass der Berechtigte durchkommt**. „Fremder
  Haushalt → 0 Zeilen" allein ginge für die mitglieds-gescopten Tabellen grün durch
  und ließe N-2 unbelegt.
- **Ökonomie:** Punkte sind ein Doppelbuchungs-Ledger. Salden sind Summen, nie
  editierbare Felder. Keine negativen Salden. Jede Bewegung referenziert ein
  Fachereignis. Property-Tests für Invarianten.
  **Append-only regelt Korrekturen im lebenden Ledger** — eine Buchung wird nie
  überschrieben, sondern gegengebucht, weil jede zwei Konten hat und ein Löschen die
  Salden *anderer* verschöbe. Deshalb verfallen Restpunkte beim Austritt als
  *Buchung* (11-S1b). Endet der **Mandant**, gibt es keine anderen Salden mehr: der
  Haushalts-Purge leert den Ledger (ADR-0086 §6).
- **Schreibpfade:** offlinefähige Entitäten ausschließlich über den Sync-Batch
  (LWW pro Feldgruppe, Idempotenz via client_op_id). Alles andere PATCH +
  If-Match. Nie beide für denselben Typ.
- **Sicherheit:** Eingaben über Pydantic; SSRF-Schutz beim Rezept-Import;
  Vault clientseitig verschlüsselt (libsodium-wasm), Server sieht nur
  Ciphertext; Secrets nie ins Repo; keine Inhalte/PII in Logs.
- **Graceful Enhancement:** Wearables/Wetter/KI sind optional. Jede Funktion
  hat einen vollwertigen Basis-Pfad ohne sie (Null-Adapter). Tests decken
  beide Pfade ab.
- **Betreiber-Grenze:** `backoffice` liest nur Aggregat-Views, nie Fachdaten.
- **Kinder & Sicherheit:** keine Wearables/Vault für Kinder-Accounts;
  Marketplace für Kinder default aus.

## Stack (Begründungen in ARCHITECTURE)
- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2,
  Postgres 18 (natives uuidv7, RLS, FTS), Redis, **taskiq** (Worker; nicht arq).
- Frontend: React 19 + TypeScript (strict), Vite, TanStack Router/Query,
  Tailwind, Radix-Primitives, Dexie (Offline), Lingui (i18n DE+EN).
- Android (spätere Phase): Kotlin + Compose, Room, WorkManager, Health Connect.
- Verträge: OpenAPI ist die einzige Quelle für Client-Typen + zod (ein
  Generator-Lauf, @hey-api/openapi-ts).
- Obs.: structlog JSON + Fehler-Referenzcodes **sind gebaut**; OpenTelemetry-Traces
  auch (Export nur bei gesetztem `CUSTODE_OTLP_ENDPOINT`). Ein `/metrics`-Endpunkt ist
  geplant (Roadmap Phase 11).
- Payments (spät): Paddle (MoR). Wetter: Open-Meteo. LLM: lokal (Ollama).

## Definition of Done (jede Einheit)
Siehe `ENTWICKLUNGSKONZEPT.md` Teil D. Kurz: Konzept-konform · Tests (inkl.
RLS-Negativ + Property bei Invarianten + beide Enhancement-Pfade) · OpenAPI +
Clients regeneriert (oasdiff ohne Breaking) · AuthZ-Matrix-Zeile · Empty/
Loading/Error · A11y (axe, Tastatur) · i18n (keine hartcodierten Strings,
BRAND_NAME-Regel) · Microcopy-Review gegen P8 · Performance im Budget · Logs ohne
PII + Fehler-Referenzcode · Migration expand/contract · MODULES-Doku + CHANGELOG
+ ggf. ADR + Eintrag in der Betreiber-Checkliste (nicht im Repo) bei jedem Betreiber-Handgriff.

**Zwei Punkte der DoD zeigen auf etwas, das es nicht gibt** — bis das behoben ist,
sind sie keine Prüfung, sondern ein Haken:
- **AuthZ-Matrix-Zeile:** `docs/security/` existiert nicht. Die Matrizen leben
  verstreut in den Modul-Dokus. Bis zur zentralen Datei: Zeile in der jeweiligen
  `docs/MODULES/<modul>.md` ergänzen.
- **Feature-Flag bei riskantem/unfertigem Sichtbarem** (Teil D): die serverseitige
  Durchsetzung je Router ist ein Roadmap-Punkt (Phase 11); bis dahin gilt der Punkt für die
  Web-Anzeige.

## Workflow mit Claude Code
1. Plan Mode zuerst; Plan gegen Konzept prüfen lassen, dann bauen.
2. Kleine, lauffähige Schritte; Tests parallel.
3. Prompts/Code-Kommentare im Code: Englisch. Doku, Commit-Bodys, ADRs,
   nutzerseitige Texte: Deutsch (UI zusätzlich Englisch via i18n).
4. Conventional Commits; Feature-Branches ≤ 2 Tage; Merge nur bei grüner CI.
5. Pro Modul eine eigene `modules/<x>/CLAUDE.md` (Zweck, Grenzen, Events, No-Gos).
6. Jeder nicht-triviale Bug → `BUGLOG.md` (Symptom → Ursache → Fix →
   Regressionstest → Lehre).
7. Erzeugt eine Einheit einen **Betreiber-Handgriff** (Zugangsdaten, fremdes Konto,
   Entscheidung, Prüfung am echten System), gehört er in die Betreiber-Checkliste (nicht im
   Repo) — mit Zustand. Erledigt wird dort **nur** auf ausdrückliche Bestätigung des
   Betreibers eingetragen, nie weil ein Deploy lief.

## Gates lokal — die Befehle, im selben Umfang wie die CI
```bash
# Backend (aus dem Repo-Root; `.` und nicht `app/ tests/` — die CI prüft auch migrations/)
uv --directory backend run ruff check .
uv --directory backend run ruff format --check .
uv --directory backend run mypy
uv --directory backend run lint-imports
uv --directory backend run pytest            # ~5 min, braucht Docker (Testcontainers)

# Web (nur aus dem Repo-Root — `--prefix` ist relativ)
npm --prefix web run lint && npm --prefix web run typecheck
npm --prefix web run test && npm --prefix web run build
npm --prefix web run size && npm --prefix web run check:pwa && npm --prefix web run lhci

# Vertrag: regenerieren und auf leeren Diff prüfen
make openapi && git diff --exit-code -- backend/openapi.json web/src/api
```
`make lint` und `make test` decken **nicht** den CI-Umfang ab (es fehlen `build`, `size`,
`check:pwa`, `lhci`, der Regen-Diff, gitleaks und trivy). Gates laufen **nach der letzten**
Änderung; ein grüner Teillauf beweist nichts.

**Ohne Docker ist die Suite rot, nicht grün** (seit 2026-08-03). Bis dahin startete jede der 75
Postgres-Testdateien einen eigenen `PostgresContainer` und endete sonst auf `pytest.skip`: ohne
Docker meldete der Lauf `563 skipped, 374 passed` und **Exit 0** — die komplette RLS-, HTTP- und
Export-Abdeckung verschwand lautlos. Jetzt gibt es **einen** Container je Session (Datenbank je
Modul aus einem migrierten Template, `backend/tests/dbfixture.py`), und `pytest_sessionfinish` in
`backend/tests/conftest.py` macht jeden Lauf rot, in dem Tests wegen fehlender Infrastruktur
übersprungen wurden. Bewusst abschaltbar mit `CUSTODE_TESTS_ALLOW_SKIPPED_INFRA=1` — eine
Entscheidung, kein Default.

## CI-Gates (blockierend, nie „temporär" deaktivieren)
`ruff check` · **`ruff format --check`** · mypy --strict · eslint · tsc --strict ·
pytest (Testcontainers-PG) · vitest · import-linter (Modulgrenzen) · Client-Regen-Diff leer ·
**oasdiff (nur auf Pull Requests)** · trivy · gitleaks · **PWA-Gate (`check:pwa`)** ·
Lighthouse-Budgets · Bundle-Size.

**axe läuft — aber nicht so, wie es hier lange stand.** Es ist kein eigener Job und deckt keine
Routen ab, sondern läuft **innerhalb von vitest über die Kern-Bausteine** (`web/src/test/a11y.test.tsx`
sagt das selbst: „*without spinning up every route's providers*"). Wer „axe (Kernrouten)" liest,
vermutet ein Gate, wo Handarbeit steht — die Routen-Abdeckung ist der Geräte-Durchgang in
`docs/MANUAL_TESTS.md` Abschnitt D.

**Diese Liste war selbst eine Zusage ohne Umsetzung.** Bis 2026-08-01 lief `oasdiff` **überhaupt
nicht** — gebaut war nur der Regen-Drift-Check, der eine *unregenerierte* Datei findet, aber keine
*kaputt gemachte* API; und `security` (gitleaks, trivy) war keine Deploy-Bedingung. Beides behoben
(ADR-0019-Nachtrag). **Am 2026-08-03 fehlten in dieser Aufzählung erneut zwei laufende Gates**
(`ruff format --check`, `check:pwa`) und eines war falsch beschrieben (axe). Wer hier eine Zeile
ergänzt, prüft, dass sie auch läuft — **und wer ein Gate baut, trägt es hier nach.**

**Lokal im selben Umfang und Modus prüfen wie die CI.** Zweimal in dieser Codebasis hat eine
lokale Prüfung grün gemeldet, was die CI rot fand — beide Male, weil lokal ein *Ausschnitt* geprüft
wurde: `ruff check app/ tests/` statt `ruff check .` (die CI prüft auch `migrations/`, wo `S608`
bei jedem f-String mit Tabellennamen anschlägt), und `gitleaks --no-git` über den Arbeitsbaum statt
über den Commit-Range. Ein grüner Teillauf beweist nichts.

## Vier Prüf-Regeln, die diese Codebasis teuer gelernt hat
- **Eine Liste, die etwas über die Datenbank behauptet, muss gegen die Datenbank geprüft werden.**
  `_RETENTION_TABLES` behauptete monatelang, drei Tabellen zu leeren; zwei fehlten die Rechte, und
  der Job starb jede Nacht (BUGLOG 2026-07-31). Dieselbe Klasse: `test_compose_env.py`,
  `test_export_policy.py`, `test_export_schema_gate.py`. **Das ORM ist dabei nicht das Schema** —
  wer nur `Base.metadata` prüft, sieht keine Tabelle und keine Spalte, die nur in einer Migration
  existiert.
- **Ein Test über einen Entzug muss erst beweisen, dass es etwas zu entziehen gab.** „Nachher kein
  Zugriff" besteht auch bei kaputtem Seed. Erst das Vorher zeigen, dann den Vorgang, dann das
  Nachher — und für jede Sperre eine Gegenprobe, dass der Berechtigte weiterhin durchkommt.
- **Ein Job, der nur bei Wirkung loggt, ist im Fehlerfall stumm.** Fehlschläge gehören als eigene
  Meldung nach oben, sonst sieht „gescheitert" aus wie „nichts zu tun".
- **Eine Prüfung, die an einer Repräsentation hängt, prüft den Begriff nicht.** Die teuerste Klasse,
  weil sie jedes Mal plausibel aussieht. **Acht belegte Fälle**, jeder an anderer Stelle:
  der Origin-Lock in `kernel/fetch` hing an der Credential-*Form* (`auth`) statt an „ist das eine
  Berechtigung" — ein Bearer wäre einem fremden Redirect gefolgt (ADR-0030); `revoke_all_sessions`
  hing an der *Session des Aufrufers* statt an „wessen Zeilen sind gemeint" und traf beim Entfernen
  null Zeilen; der Kinder-Tombstone hing an der *Rolle* statt an „kann dieses Konto ohne diesen
  Haushalt existieren" — womit ein Admin fremde Konten hätte vernichten können;
  `test_member_left_access` rief die Handler *namentlich* auf statt „alles, was registriert ist",
  und hörte beim ersten Aufteilen still auf, den ICS-Token zu prüfen; und zuletzt der
  **Refresh-Merkzettel** (11-S1g): der Scope kam aus einem Redis-Eintrag statt aus der Datenbank.
  **Der fünfte ist der lehrreichste, weil die Repräsentation ein *Cache* war** — und ein Cache
  sieht nicht wie eine Autorisierungsentscheidung aus. Setzbar von der begünstigten Person,
  haltbar dreißig Tage: das ist kein Cache, das ist eine Vollmacht.
  **Der Prüfpunkt:** Wer kann die Repräsentation setzen, und wie lange hält sie? Ist es dieselbe
  Person, die von der Entscheidung profitiert, ist sie kein Kriterium, sondern ein Hebel.
  **Die Gegenregel, die derselbe Slice gekostet hat:** ein *fail-closed lesender* Speicher darf
  nicht wie eine Ablehnung behandelt werden. `get_active_household` liefert bei einem
  Redis-Lesefehler dasselbe `None` wie bei „kein Eintrag" — wer daraufhin aufräumt, macht aus einer
  Störung von Sekunden einen dauerhaften Datenverlust.
  **Drei weitere Fälle am 2026-08-03**, alle im selben Durchgang gefunden und behoben:
  **(6)** `logout` entschied an *welches Cookie ankam* statt an „welche Sitzung ist gemeint" —
  fehlte eines, lief nur die halbe Abmeldung, und ohne Refresh-Cookie lebte die Sitzung weiter,
  während die Oberfläche „abgemeldet" zeigte (11-B3). **(7)** `NO_REFRESH_PATHS` im Web verglich
  *Zeichenketten* statt Routen-**Segmente**: `includes("/login")` traf auch die authentifizierte
  Route `/v1/auth/login-events` (11-B2). **(8)** — der lehrreichste, weil er ein **Gate** traf:
  das neue Katalog-Gate suchte nach dem *Klassennamen* `ProblemException` statt nach „erzeugt hier
  jemand einen Slug" und übersah `TokenReuseError`, das ihn per `super().__init__` setzt. Es fand
  die Lücke in sich selbst beim ersten Lauf. **Auch ein Prüfwerkzeug kann an der Repräsentation
  hängen** — und dann prüft es zuverlässig das Falsche.

## Zwei Voreinstellungen, die diese Codebasis umgedreht hat
- **Wer eine Tabelle nicht klassifiziert, bekommt zu wenig Daten — nie fremde.** `TableSpec.shared`
  muss beim Export **ausdrücklich** gesetzt werden (ADR-0083). Dasselbe beim Haushalts-Purge: eine
  gefundene, nicht eingeordnete Tabelle bricht den Lauf ab, statt zu raten (ADR-0086).
- **Eine neue Tabelle mit `household_id` gehört in *drei* Listen** — Export, Konto-Purge (je
  Spalte), Haushalts-Purge (je Tabelle). Die ersten beiden machen CI rot; die dritte hält nachts um
  04:00 den Job an. Einzelheiten in `docs/MODULES/README.md`.

## Arbeitsweise mit Prüf-Agenten (2026-08-02 teuer gelernt)
- **Prüf-Agenten dürfen im Arbeitsbaum nichts schreiben.** Zwei haben es getan: einmal wurde
  `await service.burn_access_tokens(families)` zu `_ = families`, einmal ein Funktionsrumpf zu
  `return set()` — **beide Male blieb der erklärende Kommentar bzw. Docstring stehen**. Der zweite
  Fall landete im Commit und hätte den Rollenwechsel wirkungslos gemacht.
- **`git status` findet das nicht**, weil die Datei ohnehin als geändert gilt. Vor jedem Commit
  nach einem Agenten-Lauf den **vollständigen** `git diff` der Code-Pfade lesen — besonders Zeilen,
  deren Kommentar etwas anderes behauptet als der Code darunter.
- **Zwischen „Diff gelesen" und „committet" darf nichts liegen.** Danach ist jede Fremdänderung als
  Diff gegen den Commit sichtbar statt unsichtbar im Rauschen.
- Ein Testlauf, der **parallel** zu schreibenden Agenten lief, ist kein Beleg.

## Tabu
- Modulgrenzen umgehen statt Event/Interface bauen.
- Saldo-Felder statt Ledger; negative Salden.
- Inhalte/PII/Secrets in Logs; Secrets im Repo.
- Marketingname hartcodieren.
- Neue Technologie ohne ADR mit „Bestehendes scheitert nachweislich an X".
- Rotes CI-Gate deaktivieren.
- Fremdrezept-Importe haushaltsübergreifend teilen.

## Aktueller Stand (2026-08-03)

> Dieser Abschnitt beschreibt **wo wir stehen**, nicht wie wir hierhergekommen sind. Die
> Erzählung führt `CHANGELOG.md` (Repo-Root), die Fehler `docs/BUGLOG.md`, die Entscheidungen
> `docs/adr/`. Er war einmal auf 145 Zeilen Chronik angewachsen — wer ihn wieder fortschreibt
> statt ihn zu **ersetzen**, macht ihn erneut unlesbar.

Konzept v1.0 final.

| Phase | Stand |
|---|---|
| 0–8 | technisch abgeschlossen, Betrieb auf einem Produktionsserver des Betreibers. **Offen nur operativ:** 2–4 echte F&F-Haushalte |
| 9 (CalDAV + Oura) | 🔶 — der CalDAV- und der Wearables-Strang sind fertig. **Offen: der Google-Slice** (kein Handgriff, sondern ein ungeklärter *Prämissen*-Test, s. u.) und einige Betriebs-Handgriffe (Betreiber-Checkliste, nicht im Repo) |
| 10 (Android) | ⬜ nicht begonnen — **bewusst hinter Phase 11 gestellt** |
| 11 (Hardening + Recht) | läuft. **Art. 17 vollständig gebaut**; **A1/A2 (Prüfbarkeit) und B1–B4 (alle bekannten Bugs) erledigt**; weitere Einheiten offen (s. u.) |

### Art. 17 ist fertig — der einzige große Block, der diese Phase abgeschlossen hat
Export (ADR-0083) · Austritt aus einem Haushalt (11-S1a/b) · Kontolöschung + nächtlicher Purge
(11-S1c/d, Cron 03:30) · Haushaltsauflösung (11-S1e) + Haushalts-Purge (11-S1f, Cron 04:00,
ADR-0086) · und der Refresh-Pfad, der den Scope je Rotation aus der Datenbank ableitet (11-S1g).
Der ganze Ablauf steht in `docs/LOESCHKONZEPT.md`. **Offen aus KONZEPT §5.1 ist nur noch die
Vault-Rotation** (braucht eine asymmetrische Pro-Mitglied-Identität und einen eigenen ADR).

### Google-CalDAV ist bewusst nicht begonnen
Anders als bei Oura betrifft das Unverifizierte nicht das Feld-Mapping, sondern die **Prämisse**:
ob Googles CalDAV-Endpunkt überhaupt einen OAuth2-Bearer akzeptiert. Trifft das nicht zu, ist es
kein Detail, sondern ein anderes Feature (REST-Adapter statt CalDAV-Wiederverwendung). Das
Bearer-Fundament steht. Unblocker: eine registrierte Google-App + ein `curl` (Betreiber-Checkliste).

### Was in Phase 11 fertig ist — außer Art. 17
**Die Prüfbarkeit (A) und alle bekannten Bugs (B), Stand 2026-08-03.** Sie stehen hier, weil ohne
sie kein weiterer Punkt beweisbar wäre; Einzelheiten in `CHANGELOG.md` und `docs/BUGLOG.md`.

- **A1 — die Suite kann nicht mehr still leer laufen.** Ein `PostgresContainer` je Session statt
  75, Datenbank je Modul per `CREATE DATABASE … TEMPLATE`, und `pytest_sessionfinish` macht einen
  Lauf mit infrastrukturbedingten Skips **rot**. Vorher: `563 skipped, 374 passed`, Exit 0.
- **A2 — der Fehlerkatalog ist eingeholt und genagelt.** 59 fehlende Slugs ergänzt, sechs
  Geister-Einträge richtiggestellt, Gate in beide Richtungen. Dazu der fehlende
  `Exception`-Handler: unerwartete Fehler trugen **keinen** Referenzcode.
- **B1 — der Austritt scheiterte an einem gelieferten, nicht abgerechneten Kauf** und riss die
  ganze Ökonomie-Abwicklung mit in die DLQ; bei der Haushalts-Auflösung die aller Mitglieder.
- **B2 — der 401-Replay heilte nur GETs** (+ Substring-Match auf `/login`, + stummer SSE-Kanal).
- **B3 — `logout` meldete halb ab**, und welche Hälfte, entschied ein Cookie.
- **B4 — `market.trade.reverted`** existiert, plus ein Gate über die ganze Ereignisliste.

### Offen in Phase 11
Phase 11 (Hardening + Recht) läuft. Die noch offenen Einheiten werden als GitHub Issues geführt
und dort geschlossen, sobald sie behoben sind; die Roadmap (`KONFIG/Roadmap_to_V0.1.md`) nennt Reihenfolge und
Done-Kriterien. Was fertig ist — Art. 17, A1/A2 und B1–B4 — steht oben.

### Wo was steht
- **Stand je Slice, mit Begründung** → `CHANGELOG.md` (Repo-Root)
- **Reihenfolge und Done-Kriterien** → `KONFIG/Roadmap_to_V0.1.md`
- **Fehler, Ursache, Lehre** → `docs/BUGLOG.md`
- **Wie gelöscht wird** → `docs/LOESCHKONZEPT.md`
- **Protokolle für echte Geräte/Fremdserver** → `docs/MANUAL_TESTS.md`
- **Ideen und offene Einheiten** → GitHub Issues
- **Was der Betreiber schuldet**, mit Zustand → Betreiber-Checkliste (nicht im Repo). **Erledigt
  wird dort nur auf ausdrückliche Bestätigung eingetragen** — nie, weil ein Deploy lief.
