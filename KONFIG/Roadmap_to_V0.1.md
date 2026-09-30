# Roadmap_to_V0.1 — Custode

> Begleitdokument zu KONZEPT §14. Reihenfolge ist bindend, Done-Kriterien sind
> hart. Kein öffentliches Release vor Phase 11. Querschnittspflichten (Tests,
> Doku, A11y, i18n, Obs.) gelten ab Phase 1 in jeder Einheit — siehe
> ENTWICKLUNGSKONZEPT Teil D. Haken bedeuten „erfüllt **und** im jeweiligen
> Done-Kriterium nachgewiesen".

Legende: ⬜ offen · ✅ erfüllt (und im Done-Kriterium nachgewiesen) ·
🔶 teilweise erfüllt · 🎯 Done-Kriterium der Phase.

---

## Phase 0 — Fundament  ✅ abgeschlossen (live auf dem Beta-Server)
- ✅ Repo `custode` (GitLab CE), Monorepo: `/backend` `/web` `/infra` `/docs` `/KONFIG`
- ✅ Diese sechs KONFIG-Dokumente + `CLAUDE.md` im Repo; Root- und erste
      Modul-`CLAUDE.md`-Vorlage
- ✅ `docs/`-Struktur: `ARCHITECTURE.md`, `MODULES/`, `adr/` (0001…),
      `BUGLOG.md`, `patterns.md`, `errors.md`, `NOTIFICATIONS.md` (Platzhalter)
- ✅ Backend-Gerüst: FastAPI, `kernel/` (auth, tenancy, events, ports, db, http),
      pydantic-settings, structlog, OpenTelemetry-Init
- ✅ DB: Postgres 18 lokal (Docker), Alembic-Setup, Basemodel
      (uuidv7-PK, household_id, ts, version-Trigger, deleted_at)
- ✅ RLS-Grundgerüst: App-Rolle ohne BYPASSRLS, `FORCE ROW LEVEL SECURITY`,
      Policy-Vorlage, `SET LOCAL`-Middleware
- ✅ Web-Gerüst: Vite + React 19 + TS strict, TanStack Router/Query, Tailwind +
      Design-Tokens (Token-Seed aus ENTWICKLUNGSKONZEPT A.2), Radix, Lingui
      (DE+EN), `BRAND_NAME`-Konstante
- ✅ OpenAPI-Pipeline: Schema-Export, Client+zod-Generierung (@hey-api),
      Diff-Check
- ✅ CI-Pipeline mit allen Gates (anfangs grün auf leerem Gerüst)
- ✅ `docker-compose.dev.yml`: api, worker, postgres, redis, minio, mailpit
- ✅ `make`-Targets: `dev`, `test`, `lint`, `migrate`, `seed-demo`, `openapi`
- ✅ Font-Lizenzen prüfen (Bricolage Grotesque, Inter, IBM Plex Mono — OFL)
- 🎯 CI baut & deployt leeres Gerüst auf Staging (Beta-Server); KONZEPT als v1.0
     getaggt; `make dev` startet lokal vollständig.

## Phase 1 — Plattform-Fundament  ✅ abgeschlossen (S1–S12 live)
- ✅ Auth: Registrierung (E-Mail+Argon2id), Login, Session (Access+Refresh-
      Rotation, Reuse-Detection), TOTP, Passkeys (WebAuthn), Pwned-Check
- ✅ Accounts/Profile (Anzeigename, Avatar, Arbeitszeiten, Präferenzen,
      Benachrichtigungs-Einstellungen)
- ✅ Haushalte, Mitgliedschaften, Rollen (admin/member/child/guest),
      Einladungen (Code/Link, Ablauf), Multi-Haushalt-Umschalter
- ✅ Kinder-Accounts (PIN-Login, Eltern-Consent-Flow), Admin-Kontinuität
      (letzter Admin geschützt)
- ✅ kernel/events: Outbox, Envelope (uuid7), Dispatcher, `processed_events`,
      DLQ; taskiq-Worker + Queues + Scheduler
- ✅ Notification-Inbox + SSE-Kanal pro Haushalt (Keep-Alive 20 s, Reconnect)
- ✅ Audit-Log, `login_events` (nur Landescode), Fehler-Referenzcodes (RFC 9457)
- ✅ Consent-Tabelle (append-only), `households.settings_json` + Feature-Flag-Helper
- 🎯 E2E „Haushalt erstellen → einladen → Rollen wechseln"; RLS-Negativtests
     grün (User A ↛ Haushalt B); jede Fehlermeldung trägt Referenzcode;
     `login_events` aktiv.

## Phase 2 — Rezepte + Nutrition-Pipeline  ✅ abgeschlossen (S1–S7 live)
- ✅ Kanonische Zutaten, Einheiten/Umrechnung, Mapping zu USDA + Open Food Facts
- ✅ Start-Korpus ~500 Zutaten kuratiert; manuelles Override-UI
- ✅ Rezept-CRUD, strukturierter Editor, Fotos, Tags, Skalierung
- ✅ Import-Pipeline: JSON-LD → recipe-scrapers → LLM-Fallback → Review-Screen;
      SSRF-Schutz (DNS-Pinning, Schema-Whitelist, Limits, Redirect-Cap)
- ✅ Kochmodus (Wake-Lock, Schritt-Fokus, Zutaten im Schritt, Timer)
- ✅ Nährwertberechnung je Rezept mit Konfidenz-Kennzeichnung
- ✅ 15 eigene Starter-Rezepte (DE/EN) als Seed
- 🎯 20 reale URLs ≥ 90 % ohne Handarbeit importiert; Stichproben-Nährwerte
     plausibel; Kochmodus auf Tablet bedienbar.

## Phase 3 — Einkaufsliste  ✅ abgeschlossen (S1–S8 live)
- ✅ Listen, Posten (eigene Zeile, `checked` eigenes Feld), Mengen, Notizen,
      mehrere Listen, Markt-Kategorien (anpassbare Reihenfolge)
- ✅ Generierung aus Mealplan (Aggregation, Einheiten-Merge) — kommt in Ph. 6
      live, Schnittstelle hier vorbereiten
- ✅ Basics-Liste; Schnellkatalog (Kacheln aus Historie+Basics, 1-Tap,
      lernende Kategorie); Kachel/Liste-Toggle
- ✅ Reservieren von Posten; kollaborativ live (SSE)
- ✅ Web-Offline: Dexie-Tabellen + outbox_ops; Sync-Batch-Endpoint v1
      (LWW pro Feldgruppe, Idempotenz); Resync-Pfad
- 🎯 Zwei Browser haken parallel ab ohne Verlust; Offline-Abhaken synct nach
     Reconnect korrekt (Sync-Property-Tests grün).

## Phase 4 — Aufgaben + Gamification + Marketplace + Zuruf-Basis  ✅ abgeschlossen (S1–S9b live)
- ✅ Task-Templates/-Instanzen (**P4-S1 ✅**: CRUD + Erledigen-Zustandsmaschine,
      PATCH+If-Match, `task.completed`-Event), RRULE, Rotation (fair/fix/open) (offen),
      Räume + Verfalls-Indikator + Heatmap (**P4-S6 ✅**: `rooms` + `room_id`,
      berechnete Heatmap grün/gelb/rot)
- ✅ Punkte-Ledger (Double-Entry) (**P4-S2 ✅**: append-only `points_ledger`,
      synchrone Gutschrift via economy.api, Saldo/Korrektur, Property-Tests),
      Belohnungskatalog + Einlösung (**P4-S3 ✅**: rewards/redemptions, Einlösen mit
      Deckung/Stock/Cooldown, Admin-Bestätigung), Wert-Verfall (−10 %/Tag, min 50 %)
      (**P4-S4 ✅**: bei Erledigung, `awarded_points`, Property-Tests; per-Haushalt-Config folgt),
      Danke-Punkte (Cap), Wochen-Challenge (Rollup, Preis ohne Abzug)
      (**P4-S5 ✅**: Danke `member→member` mit Wochen-Cap; Challenge-Live-Wertung aus dem Ledger;
      Challenge-an/aus + Gewinner-Belohnung + Kinder-Wochenziele offen)
- ✅ Fairness-Konto (Abwesenheit herausgerechnet) (**P4-S7 ✅**: `fairness_load` 30-Tage-Last
      aus dem Ledger, aufsteigend, Marketplace-Tiebreaker; Abwesenheit = Phase 5)
- ✅ Marketplace: Escrow, Auto-Accept (Fairness-Tiebreaker), Ablehnungsrecht,
      Erledigung→Settle, Verfall→Rückfall, Rückzug; Kinder default aus
      (**P4-S8a ✅**: Listing/Escrow + Statusmaschine open→accepted→settled/withdrawn,
      manueller Settle, Property-Test Σ inkl. Escrow.
      **P4-S8b ✅**: Auto-Übernahme-Regeln + Fairness-Tiebreaker, synchron, Audit A-05.
      Auto-Settle + Verfall→Rückfall-Cron = späterer Worker-Slice)
- ✅ Zuruf-Basis: Regel-Parser (offline), Routinen, Aktionsketten
      (Posten→Task via `on_item_checked`); Vorschlagskarte; Inbox-Triage
      (**P4-S9a ✅**: capture-Modul + deterministischer Regel-Parser + Inbox-Triage,
      Confirm legt Posten/Task serverseitig an, ADR-0038.
      **P4-S9b ✅**: Aktionsketten — Folge-Klausel erzeugt Posten + armed Task,
      `shopping.item.checked` (item-granular) → capture-Handler aktiviert via tasks.api,
      Composition-Root-Registrierung, ADR-0039. **Deo-Fall E2E ohne LLM erfüllt.**
      Routinen + Scheduling-Hinweis = S9c)
- ✅ Property-Tests: Saldensumme inkl. Escrow konstant & nie negativ (S2/S8);
     Marketplace-Statusmaschine vollständig (S8); Deo-Fall E2E ohne LLM (S9b).
     **Alle drei Phase-4-Done-Kriterien erfüllt.**

## Phase 5 — Kalender + Scheduling + Wetter  🔶 gebaut und live; 🎯 offen (ICS extern unverifiziert)
- ✅ Persönlicher + Haushaltskalender, Layer-System, RRULE, Event-Flags
      (Abwesenheit/Gäste)
      (**P5-S1 ✅**: `calendar`-Modul — Event-CRUD, Layer-System (household/personal,
      query-seitige Sichtbarkeit ADR-0040), PATCH+If-Match, RLS, Web-Agenda.
      **P5-S2 ✅**: RRULE-Serien (RFC-5545 via python-dateutil, ADR-0041; gefensterte,
      DST-sichere Expansion).
      **P5-S4 ✅**: Event-Flags `kind` (normal/absence/guest) + `calendar.api.list_absences`-Naht.
      **P5-S5 ✅**: Einzel-Occurrence-Ausnahmen — `exdates` (EXDATE, 0036), instant-genaue Filterung
      + ICS-EXDATE, Action-Endpoints cancel/restore mit Mengen-Semantik ohne If-Match (ADR-0043).
      **P5-S10 ✅**: Einzel-Occurrence verschieben — `overrides` (jsonb, 0040), expand liefert
      `original_start`, move/reset-Endpoints, ICS-RECURRENCE-ID, ADR-0048)
- ✅ ICS-Export (Secret-Feed) + ICS-Import
      (**P5-S3 ✅**: ICS-Abo-Feed — `calendar_feeds` Secret-Token, unauth read-only
      `GET /feed/<token>.ics`, maint-Lookup + Owner-Scope, RRULE im VEVENT, ADR-0042.
      **P5-S6 ✅**: ICS-**Import** als Datei-Upload (kein URL-Fetch → keine SSRF, ADR-0044), reiner
      Parser `ics_parse.py`, Dedup über `source_uid` (0037). Webcal-Abo/Pull = späterer Slice)
- ✅ Scheduling-Engine (Arbeitszeiten, Routinen, Wetter-Signal, Fairness),
      Klartext-Begründung, opt-in Auto-Eintrag
      (**P5-S8a ✅**: `scheduling`-Modul — reine Slot-Engine, calendar.api-Naht `list_busy_intervals`,
      `GET /v1/scheduling/slots` (read-only), Begründungs-Codes + Web-i18n, opt-in Eintrag via
      Create-Route, ADR-0046. Arbeitszeiten feste UTC-Stunden; Routinen/Wetter/Fairness/Auto = später.
      **P5-S8b ✅**: Abwesenheit berücksichtigen (Synergie S-09) — `list_absence_intervals`-Naht,
      eigene `absence`-Zeiten blocken Slots, Code `avoids_absence`.
      **P5-S8c ✅**: Regen-Hinweis (Synergie S-15) — `weather.api.get_forecast`-Naht, Slot an
      Regentag (≥60 %) trägt Code `rain_warning`; Wetter blockiert nie, graceful ohne Wetter)
- ✅ Open-Meteo-Adapter + Null-Adapter; Standort grob pro Haushalt; Caching
      (**P5-S7 ✅**: `weather`-Modul — `weather_locations` (0038, RLS), Provider-Adapter
      OpenMeteo + Null (Graceful Enhancement, beide Pfade getestet), reiner Parser, fixer Host
      (keine SSRF), Redis-Cache, `GET /v1/weather` + `PUT/DELETE /location` (admin), Web-Karte
      flag-gegated, ADR-0045. **P5-S14 ✅**: Geocoding `GET /weather/geocode` (Ortsname → Koordinaten,
      fixer Host/keine SSRF, Cache). `weather.api`-Naht für Scheduling ✅ P5-S8c)
- ✅ Synergien S-09/10/13/15/17 (Abwesenheit, Engpass→Marketplace, Heatmap-
      Aktion, Regen-Hinweis, Liste-reif→Slot) — **alle erledigt**
      (**S-09 ✅** P5-S8b · **S-15 ✅** P5-S8c · **S-13 ✅** P5-S11: ad-hoc Task direkt an Raum
      (`task_instances.room_id`, 0041), Heatmap-Karte „+ Aufgabe", ADR-0049.
      **S-17 ✅** P5-S12: volle Liste → Nudge → Scheduling-Panel vorbefüllt.
      **S-10 ✅** P5-S13: eigene überfällige Aufgaben → Nudge „im Marktplatz anbieten")
- 🎯 DST-Testsuite grün (**P5-S9 ✅**: `tzid`-Verankerung, ADR-0047, `test_calendar_dst.py`);
     Vorschläge mit Begründung (**S8a-c ✅**); Wetter-Ausfall degradiert sauber/Basis-Pfad
     (**S7 ✅**, Null-Adapter); ICS-Feed in Google/Nextcloud verifiziert (manuell,
     offen — interne Betriebsliste, nicht im Repo; das Protokoll steht in `MANUAL_TESTS.md` Abschnitt C); DST-korrektes ICS via `TZID`+`VTIMEZONE`
     **✅ P9** (explizite RDATE-Übergänge aus der tz-Datenbank statt geratener Regel).

## Phase 6 — Mealplanner inkl. Automatik  ✅ abgeschlossen (live auf dem Beta-Server)
- ✅ Wochenplan-UI (Drag&Drop, Slots konfigurierbar), „Wer kocht"
      (**P6-S1 ✅**: `mealplanner`-Modul — `meal_plans`/`meal_slots` (0042, RLS), Slot =
      Rezept-xor-Freitext + cook/note, Rezept über recipes.api (kein FK), `mealplan.updated`-Event,
      Wochen-Grid-UI mit Inline-Edit, ADR-0050. Drag&Drop + konfigurierbare Slots = später.
      **P6-S6 ✅**: „Woche übernehmen" — `POST /v1/mealplan/copy` kopiert die Vorwoche non-destruktiv
      in die leeren Zellen, „Aus Vorwoche übernehmen"-Button)
- ✅ Philosophie-Profile, Slot-Regeln, Constraint-Automatik mit Begründung,
      „neu würfeln", persönliche Portionsfaktoren
      (**P6-S4 ✅**: „neu würfeln" je Slot — `POST /v1/mealplan/suggest`, reine
      `pick_least_recently_cooked` (Wiederholungs-Sperre über `last_cooked_at`, `lockout_days`,
      meidet Verplantes), 422 ohne Kandidat, 🎲-Button, ADR-0052.
      **P6-S5 ✅**: „Woche würfeln" — `POST /v1/mealplan/suggest-week`, `suggest_many` füllt alle
      leeren Zellen einer Mahlzeit distinkt, best-effort (kein 422), „Woche würfeln"-Button.
      Profile/Slot-Regeln/Portionsfaktoren = später)
- ✅ `mealplan.updated` → Diff-basierte Listen-Regeneration (Ph. 3 Schnittstelle)
      (**P6-S2 ✅**: `POST /to-shopping` — Zutaten der Wochen-Rezepte über `shopping.api`-Sync-Batch in
      die Liste, deterministisch/idempotent, `source="mealplan"`. Mengen-Merge + Auto-Diff = später)
- ✅ Synergien S-01/02/03/07/08 (Event-Flags, Vorbereitungs-Tasks, Koch-Task,
      Wunschgericht, Gäste-Präferenzen)
      (**P6-S8 ✅** (S-01 Teil 1): Abwesenheits-Hinweis — `GET /v1/mealplan.absent_days` aus
      `calendar.api.list_absence_intervals`, reine `absence_weekdays`, „abwesend"-Badge, ADR-0054;
      Automatik/Portionen/Gäste = später.
      **P6-S9 ✅** (S-02): Vorbereitungs-Task am Vortag — `POST /v1/mealplan/slot/prep-task`, reine
      Vorlauf-Heuristik `needs_prep` (auftauen/marinieren/…) → `tasks.api`-Aufgabe, ADR-0055; echte
      `due_at`-Terminierung = später)
      (**P6-S3 ✅**: „zuletzt gekocht"-Historie — `recipes.last_cooked_at`/`cooked_count` (0043),
      `mealplan.cooked` + synchroner `recipes.api.mark_cooked` (ADR-0051); Fundament der
      Wiederholungs-Sperre.
      **P6-S7 ✅** (Synergie S-03 Teil 1): „Koch-Task aus Slot" — `POST /v1/mealplan/slot/cook-task`
      legt „Kochen: <Gericht>" via `tasks.api.create_personal_task` an (an cook_id/Caller), ADR-0053;
      Rotation/Fairness/Punkte fürs Kochen = später)
- 🎯 Auto-Wochenpläne für 3 Profile erfüllen Nährwertziele ±10 % ohne
     Allergie-Verstöße (Property-Tests).
     (**P6-S10 ✅** Fundament: Wochen-Nährwert-Übersicht — `GET /v1/mealplan/nutrition` summiert die
     pro-Portion-Makros der geplanten Rezepte über `recipes.api.recipe_macros` (reine `sum_macros`),
     ADR-0056.
     **P6-S11 ✅** ±10%-Bewertung: `?target_kcal=` → `verdict` (under/on_target/over) via reiner
     `evaluate_target` — das Bewertungs-Primitiv für den Auto-Planer.
     **P6-S12 ✅** Kern-Automatik: `suggest-week?target_kcal=` füllt mit den Rezepten nächst am
     kcal-Ziel (reine `pick_for_target` + Hypothesis-Property), ADR-0057.
     **P6-S13 ✅** „ohne Allergie-Verstöße": `exclude_tag`-Filter (reine `has_excluded_tag`) vor der
     Auswahl, ADR-0058 — mit `target_kcal` kombiniert = „±10 % ohne Allergie-Verstöße". Persistente
     Philosophie-/Allergie-Profile + kanonischer Allergen-Abgleich (ingredient_id) = Folge-Slices)

## Phase 7 — Briefe + Anleitungen + Notizen + Vault + Zuruf-LLM  ✅ abgeschlossen (live auf dem Beta-Server)
- ✅ Briefe (Betreff/Text/Anhang, Gelesen-Status, „Kümmerst du dich?"→Task)
      (**P7-S4 ✅**: `messaging`-Modul-Fundament — `letters` + `letter_reads` (Migration 0046, RLS-
      Negativtest je Tabelle), Rundbrief/adressiert, Gelesen-Status als eigene Tabelle (ADR-0062),
      `GET/POST /v1/letters` + `/unread-count`, `letter.*`-Events→SSE, Web `/letters` (Inbox + Schreiben),
      16. import-linter-Contract.
      **P7-S5 ✅**: „Kümmerst du dich?"→Aufgabe — `POST /v1/letters/{id}/to-task` via `tasks.api`
      (non-destruktiv, an den Auslöser), ADR-0063.
      **P7-S12 ✅** (Empfänger-Picker, Web): gezielte Empfängerauswahl beim Schreiben (Checkbox-Liste
      der Mitglieder außer einem selbst; leer = Rundbrief), Hinweistext wechselt, i18n DE/EN; Backend-
      `to_ids` existierte bereits.
      **P7-S21 ✅** (Kommentare am Brief, Web): `CommentThread` (`objectType="letter"`) im Brief-Detail
      eingebettet — ruhige Diskussion ohne neuen Brief; reine Frontend-Einbettung der generischen
      comments-Infrastruktur. Anhang / Notification-Fan-out = später)
- ✅ Kommentare an Objekten + @-Mentions; Notizen (+ Dashboard-Pin,
      Konvertieren-zu, 5 Versionen)
      (**P7-S7 ✅** (Kommentare): `comments`-Modul-Fundament — generische `(object_type, object_id)`-
      Threads (Migration 0048, RLS-Negativtest, 18. Contract), `GET/POST/DELETE /v1/comments`
      (Löschen nur Autor), `comment.*`-Events→SSE, wiederverwendbare Web-`CommentThread` (an `/guides`),
      ADR-0065. @-Mentions / Notifications = später.
      **P7-S20 ✅** (Reaper): Outbox-Handler auf `recipe/note/guide.deleted` → `purge_for_object`
      soft-deletet verwaiste Kommentare **und** Links (am Worker-Composition-Root, nur per Event-Name
      gematcht, idempotent; `task` ausgeklammert — Template-Event vs. Instanz-Endpunkte).
      **P7-S18 ✅** (Editieren): `PATCH /v1/comments/{id}` (If-Match, `version`=ETag, nur Autor → 403,
      412 stale, neues `comment.updated`-Event); `CommentResponse` trägt jetzt `version`+`updated_at`
      → Web-Inline-Edit ohne Einzel-GET; additive OpenAPI, keine Migration, ADR-0029.
      **P7-S1 ✅**: `notes`-Modul-Fundament — `notes` (Migration 0044, RLS-Negativtest), Titel +
      Markdown-Body + `pinned`, PATCH+If-Match (ETag), `note.*`-Events→SSE, `/v1/notes`-CRUD,
      Web `/notes` (Liste + Editor + Pin), 15. import-linter-Contract, ADR-0059.
      **P7-S2 ✅**: Versions-Historie (5 Versionen) — `note_versions` (Migration 0045, RLS), Snapshot
      vor jeder Inhaltsänderung + Kappung auf 5 (Pin-Toggle erzeugt keine Version), `GET …/versions`
      + `POST …/restore` (rückgängig machbar), Web-„Versionen"-Liste, ADR-0060.
      **P7-S3 ✅**: „Konvertieren-zu Aufgabe" — `POST /v1/notes/{id}/to-task` via `tasks.api`
      (non-destruktiv), ADR-0061. Weitere Zieltypen = später.
      **P7-S9 ✅** (Web): generische `CommentThread` + `LinksPanel` jetzt auch an Rezept-Detail
      (`recipe`) + Notiz-Editor (`note`) eingebettet — Infrastruktur an 3 Objekttypen aktiv.
      **P7-S10 ✅** (Web, **Dashboard-Pin**): „Heute"-Startseite zeigt angepinnte Notizen als erste
      echte Kachel (`GET /v1/notes?pinned=true`), Klick → `/notes`; Empty/Loading/Error, i18n DE/EN.)
- ✅ Anleitungen (Markdown, Anhänge, Kategorien, FTS deutsch, ACL,
      Ansprechpartner), `object_links` (Rezept↔Anleitung, Task↔Anleitung,
      Anleitung↔Vault ohne Inhalt)
      (**P7-S6 ✅**: `guides`-Modul-Fundament — `guides` (Migration 0047, RLS-Negativtest), Titel +
      Markdown + Kategorie + Tags, **deutsche FTS** über GENERATED `search_tsv` + GIN (`?q=` ranked,
      Stemming), PATCH+If-Match, `guide.*`-Events→SSE, `/v1/guides`-CRUD, Web `/guides` (Suche + Editor),
      17. import-linter-Contract, ADR-0064.
      **P7-S22 ✅** (Anhänge, ADR-0069): 1:n `guide_attachments` (Migration 0052, RLS-Negativtest);
      Bytes im Blob-Storage (ADR-0033), DB nur Metadaten + server-generierter Key; Upload/Liste/
      Download/Löschen, 503 ohne Storage (graceful), 25-MiB-Cap; Anleitung-Löschen kaskadiert (Blob +
      Zeile); Web-`AttachmentsPanel`. ACL = später.
      **P7-S11 ✅** (Ansprechpartner): additive, nullable `guides.contact_id` (Migration 0050, nacktes
      Mitglieds-UUID, kein FK — clientseitige Namensauflösung über `/v1/household/members`); PATCH-Clear
      via `model_fields_set`; Web-Mitglieder-`<select>` im Editor.)
      (**P7-S8 ✅** (`object_links`): `links`-Modul-Fundament — generische, **richtungsunabhängige**
      Verknüpfungen zwischen zwei `(type, id)`-Endpunkten + `relation` (Migration 0049, RLS-Negativtest,
      19. Contract). Kanonische Endpunkt-Ordnung + Partial-Unique-Index (keine symmetrischen Duplikate),
      idempotenter Re-Link, Selbst-Link→422. `GET/POST/DELETE /v1/links`, `link.*`-Events→SSE,
      wiederverwendbares Web-`LinksPanel` (an `/guides`), ADR-0066.
      **P7-S19 ✅** (Objekt-Picker, Web): Ziel per Typ-Filter + Namens-Dropdown der vorhandenen Objekte
      statt roher UUID; eigenes Objekt ausgeschlossen (Self-Link 422); bestehende Links zeigen den
      Ziel-Namen (Fallback Kurz-ID bei gelöschtem Ziel). Reine Frontend-Komposition, Helfer
      unit-getestet. **Reaper verwaister Links** = ✅ P7-S20 (siehe comments). ACL / Anleitung↔Vault =
      später.)
- ✅ Vault: libsodium-wasm, Haushaltsschlüssel-Umschlag, separate Passphrase
      (Argon2id), Recovery-Code, Schlüssel-Rotation bei Austritt, CSP-Härtung
      (**P7-S13 ✅** (Backend-Fundament, ADR-0067): `vault`-Modul — `vault_key_envelopes` +
      `vault_items` (Migration 0051, RLS-Negativtest je Tabelle, 20. Contract). **Server nur
      Ciphertext** (opake Base64 + Client-JSON-Meta, auch der Name verschlüsselt, kein Klartext/PII/Log);
      Umschläge pro Mitglied (Passphrase) + Recovery, `key_version`. `GET/PUT /v1/vault/keys`,
      `/items`-CRUD (Summary ohne ciphertext, PATCH+If-Match). **Kinder/Gäste ausgeschlossen**.
      `vault.*`-Events→SSE. Web-Krypto (libsodium-wasm: Passphrase/Unlock/Recovery) = S14,
      Rotation/CSP = S15.
      **P7-S14a ✅** (Web-Krypto-Modul): `vault/crypto.ts` auf libsodium-wasm (dynamisch importiert,
      Lazy-Chunk) — Argon2id-Wrap-Key (INTERACTIVE) + XSalsa20-Poly1305-Secretbox; Name separat
      verschlüsselt (Liste zeigt Titel ohne Body); `vault/queries.ts` (Items mit ETag/If-Match);
      Realtime-Entity `"vault"`; Krypto-Round-Trip-Unit-Tests. Vault-Route-UI (Setup/Unlock/Items) = S14b.
      **P7-S14b ✅** (Vault-Route-UI): `/vault` — Einrichten (Passphrase setzen → Schlüssel + Passphrase-
      & Recovery-Umschlag, Recovery-Code einmalig angezeigt), Entsperren (Passphrase, Schlüssel nur im
      Speicher), Einträge anlegen/auflisten (Namen entschlüsselt)/aufklappen (Body on-demand)/löschen.
      libsodium-wasm = separater Lazy-Chunk (~535 kB, nicht im Haupt-Bundle). Nav-Link, i18n DE/EN.
      **P7-S15a ✅** (Recovery + Passphrase-Wechsel): „Passphrase vergessen?" entsperrt über den
      Recovery-Umschlag (Recovery-Code), danach neue Passphrase setzen; Passphrase-Wechsel auch im
      entsperrten Tresor (re-wrap). Erfüllt „Recovery real durchgespielt" aus dem 🎯.
      **P7-S15b ✅** (CSP-/Security-Header): Caddy setzt nosniff/X-Frame-Options/Referrer-Policy/
      Permissions-Policy (erzwingend) + CSP als **Report-Only** (nicht-brechend; Erzwingung nach
      Beobachtung).
      **P7-S16 ✅** (Einträge bearbeiten): Vault-Item inline editierbar (neu verschlüsseln +
      PATCH+If-Match) — Item-CRUD vollständig. Verbleibend: Schlüssel-Rotation bei Austritt (asymm.
      Identität, eigener ADR), CSP-Erzwingung, Zuruf-LLM.)
- ✅ Zuruf-LLM-Anreicherung (Ollama, JSON-Schema, Review), Formulierungshilfen
      (**P7-S17 ✅**, ADR-0068): optionale LLM-Verfeinerung des Zuruf, **Graceful Enhancement** —
      default aus (`NullLlm`), der deterministische Parser bleibt Basis-Pfad + Quelle der Wahrheit
      fürs Routing; das LLM (lokal, Ollama) füllt via reinem `merge_enrichment` nur leere
      Freitext-Slots + ergänzt Tags. Schema-validiert, nie ungeprüft persistiert, keine PII in Logs,
      kein SSRF (Server-Config). Verbleibend in Phase 7: Schlüssel-Rotation bei Austritt (asymm.
      Identität, eigener ADR), CSP-Erzwingung.
- 🎯 Vault-Krypto selbst-auditiert, Recovery real durchgespielt; FTS liefert
     brauchbare Treffer; Vault-Inhalte nie in LLM/Logs.

## Phase 8 — Web-Polish + Betreiber-Konsole v1 + Friends&Family-Beta  ✅ technisch abgeschlossen; 🎯 offen nur operativ (2–4 echte F&F-Haushalte)
- ✅ „Heute"-Dashboard (S-21), Onboarding-Flow (Presets Solo/Familie/WG),
      Empty/Loading/Error überall, Mobile-Browser-QA, A11y-Durchgang
      **P8-S1 ✅** („Heute"-Dashboard): `/today` aggregiert modulübergreifend (Aufgaben heute,
      heutige Mahlzeiten, Termine heute via expandiertem Kalender-Window, offener Einkauf,
      Punkte-Saldo, angepinnte Notizen) in wiederverwendbaren `DashboardTile`-Kacheln mit
      Empty/Loading/Error + A11y-Landmarks; Nav-Eintrag „Heute". Reine Frontend-Slice.
      **P8-S2 ✅** (Onboarding-Presets): frischer leerer Haushalt → Schnellstart Solo/Familie/WG seedet
      Räume + Aufgaben-Vorlagen in einem Schritt (`OnboardingPresets` + kuratierte bilinguale
      `lib/presets.ts` + `useApplyPreset` über bestehende tasks-Endpunkte). Self-hiding, reine Frontend-Slice.
      **Mobile-/Prod-Browser-QA ✅** (2026-07-08): eingeloggte Playwright-Matrix am Deploy —
      Registrierung E2E, 24 Routen × {mobil Pixel-7, desktop} × {hell, dunkel}, 96 Shots +
      Konsolen-/HTTP-Fehler, Auswertung mehrperspektivisch. Kernbefund gefixt (#132: frischer
      Login ohne Haushalts-Kontext → 403-Wand; jetzt Auto-Scope auf einzige Mitgliedschaft +
      `NoHouseholdState`; dabei Security-Fix: soft-gelöschte Mitgliedschaft erlaubte Re-Switch,
      s. BUGLOG). Dark-/Kontrast-Politur (#134): `text-laurus`-Sweep, Button-Hierarchie/AA,
      native Controls dark. **Slice-C-Politur ✅** (2026-07-22): echte `danger`-Button-Variante
      (Rost) + Trio-Fehlerzweige Einkaufsliste/Kochmodus.
- ✅ **Wochen-Digest (P8-S7)** — Worker-Cron, maint-Fan-out, Graceful Null-Mail, Aufgaben-
      Zusammenfassung; **Admin-Abschaltung (P8-S7b)**; `docs/NOTIFICATIONS.md` mit dem ersten
      konkreten Kanal gefüllt (ADR-0070). Mahlzeiten-Inhalt = spätere Slice.
- ✅ **Feedback-Kanal (P8-S5)** — Modul `feedback` (RLS), Submit/Liste, Fehler-Referenzcode;
      **Betreiber-Inbox (P8-S8e)** via `ops_feedback`-View; **opt-in Diagnose-Ringpuffer ✅**
      (`feedback.diagnostics`, Migration 0062, content-frei + `extra="forbid"`, in Inbox sichtbar);
      **„Was ist neu" ✅** (Release-Notes unter `/neuigkeiten`); **Issues-Weiterleitung ✅**
      (GitHub statt GitLab, Best-Effort mit Null-Adapter, ADR-0076, Slice 5h).
- ✅ **Betreiber-Konsole v1** — DB-Fundament (Aggregat-Views + Rollen-Trennung,
      P8-S7a, ADR-0071), Operator-Auth (Passwort+**TOTP**, opake Redis-Bearer-Session, P8-S7b,
      ADR-0072; **Passkey ✅** WebAuthn, Slices 5k/5l), KPI-Endpunkt (P8-S7c), append-only
      `audit_log` (P8-S8a, ADR-0073), auditierte Aktionen Banner (P8-S8b) + globale Flags (P8-S8c),
      Support-Suche (P8-S8d) + Feedback-Inbox (P8-S8e), System-Health/Build-Info.
      **`/ops`-Frontend ✅** (eigenes Bundle/Subdomain, Bearer-Auth, ADR-0074: Login → KPI-Dashboard →
      auditierte Banner/Flags → Support-Suche + Feedback-Inbox, S-OPS-FE-a…d).
      **Audit sensibler Reads ✅** (Slice 5i, ADR-0073) · **Operator-Verwaltung im UI ✅** (Slice 5j;
      Anlegen bewusst CLI/Seed) · **Audit-Log-Ansicht ✅** (S-OPS-FE-g).
- ✅ **Sanftes Löschen** — Retention-Reaper (30-Tage-Hard-Delete, P8-S3, ARCH §9) + **Papierkorb +
      Wiederherstellen** (P8-S4, Notizen; weitere Tabellen folgen mit ihren Trash-Sichten).
      **DSGVO-Texte v1 + Impressum (P8-S6).**
- ✅ **A11y** — statisches `jsx-a11y` + **Laufzeit-axe-Gate** für Kern-Bausteine (P8-S9a),
      ausgeweitet auf `Field`/`ErrorState`/`ReleasesPage`; **Lighthouse-Budgets ✅** (CI-Gate,
      Slices 5e/5f), **Mobile-QA ✅** (Playwright-Matrix, s. o.); **Trio-Gesamtdurchgang ✅**
      (Route-Audit 2026-07-22: Fehlerzweige Einkaufsliste + Kochmodus nachgezogen, alle übrigen
      Datenrouten trugen das Trio bereits — Slice C).
- 🎯 Lighthouse ≥ 90/95/95/90 ✅ **gemessen** (Slice 5e/5f; das CI-Gate steht bewusst als **Boden** bei 0.88 Performance — ein Budget, das exakt auf dem Zielwert sitzt, wird bei jeder Messschwankung rot und damit ignoriert); Konsole zeigt echte Zahlen ✅;
     Soft-Delete + Restore ✅; Mobile-QA ✅. **Offen nur operativ: 2–4 echte Haushalte aktiv
     (F&F-Einladungen = Betreiber-Handgriff).**

## Phase 9 — CalDAV-Sync + Oura-Cloud (begonnen 2026-07-08)
- 🔶 CalDAV-Zwei-Wege-Abos (Nextcloud/Google/iCloud) als Layer + „belegt"-Signal
      (**9-S1 ✅**: `kernel/crypto` — server-seitige Credential-Verschlüsselung (Fernet,
      `CUSTODE_CRYPTO_KEY`, ADR-0077) als Fundament für `creds_enc`/`tokens_enc`.
      **9-S2 ✅** (2026-07-22): Datenmodell + CRUD — `external_calendar_subscriptions`
      (Migration 0065, RLS + maint-Enumeration für den Cron), write-only-Credentials als
      SecretBox-JSON, owner-only-API `/v1/calendar/subscriptions` (PATCH+If-Match, 409-Duplikat,
      beide Graceful-Pfade getestet).
      **9-S3 ✅** (2026-07-23, ADR-0079): Pull-Sync — 15-min-Cron spiegelt Abos als
      `personal`-Events (`subscription_id`, Migration 0066), REPORT+defusedxml,
      `safe_request`-SSRF-Guard, read-only bis 9-S4 (409), Fehler-Kategorien +
      Kill-Switch, Radicale-Tests (Container gepinnt) + Dev-Compose-Radicale.
      **9-S4 ✅** (2026-07-23, ADR-0080): Write-back — zwei-Wege, remote-first:
      Create-into-Abo (`EventCreate.subscription_id`), Edit per GET-modify-PUT
      (Property-Erhalt bewiesen), Delete mit If-Match; Konflikt = 409 + Sync als
      Reconciliation; href-Pfad-Guard (Credential-Exfil geschlossen).
      **Web-Abo-Verwaltung ✅** (2026-07-23): Abo-Sektion auf der Kalender-Seite
      (CRUD, write-only-Credentials, Status je Fehlerkategorie), Extern-Badge +
      Aktions-Gating in der Agenda, Ziel-Kalender-Select fürs Anlegen ins Abo,
      i18n-Paritäts-Guard. CalDAV ist damit komplett ohne API-Handgriffe nutzbar.
      Slice-Reihenfolge: ~~Datenmodell+CRUD~~ → ~~Pull-Sync~~ → ~~Write-back~~ →
      ~~Web-Abo-Verwaltung~~; Google = OAuth-Folge-Slice, teilt Infra mit Oura)
- ✅ Oura OAuth2 (kein PAT), Art.-9-Consent pro Datentyp, Retention-Jobs,
      Wearable→Scheduling/Mealplan (additiv), Kill-Switch
      (**9-S5 ✅** (2026-07-26, ADR-0081): OAuth-Fundament + Art.-9-Consent — Modul `wearables`,
      `wearable_connections`/`wearable_daily` (Migration 0069) mit **mitglieds-gescopter RLS**
      (`household_id` UND `member_id` im Prädikat; ein Mitbewohner, auch ein Admin, sieht
      DB-seitig 0 Zeilen — N-2 ist damit erzwungen, nicht zugesichert), harte Löschung statt
      Tombstone (`CHECK deleted_at IS NULL`), `consents.action` grant/revoke (Migration 0068,
      Append-only bleibt: Widerruf = neue Zeile), Authorization-Code-Flow mit gehashtem
      Single-use-`state` in Redis + unauthentifiziertem 302-Callback samt Rollen-Neuprüfung,
      `tokens_enc` als SecretBox-Wert, Kill-Switch + serverseitige Flag-Erzwingung.
      **9-S6 ✅** (2026-07-27): Ingest-Cron + Retention — `OuraClient` (v2-Endpunkte, defensives
      Mapping: Bereichsverletzungen werden verworfen statt geklemmt), Nacht-Cron `20 4 * * *`
      (Aufzählen unter maint, **schreiben pro Mitglied unter `scoped_session`** — so hält N-2
      auch für einen Hintergrundjob), Reihenfolge Rolle → Refresh → Fetch → Consent-Filter
      (Rollen-Nachlauf **vor** jedem ausgehenden Request, damit eine Herabstufung auch den
      Verkehr stoppt), Refresh-Rotation mit `needs_reauth` statt nächtlichem Hämmern,
      90-Tage-Retention als **eigener** Job `40 3 * * *` (läuft auch bei Kill-Switch aus;
      DELETE-Grant nur auf `wearable_daily`, Migration 0070).
      **9-S7 ✅** (2026-07-27): Scheduling-Signal (Synergie S-14) — Naht
      `wearables.api.recovery_signal` gibt **ein Boolean, nie einen Score** (ein roher
      Gesundheitswert über einer Modulgrenze *ist* das Gesundheitsdatum), immer mit
      `member_id=viewer_id`; die mitglieds-gescopte RLS liefert für jede fremde id nichts —
      per Test belegt. Slots ab 90 min auf einem Erschöpfungstag tragen den Code `low_recovery`;
      die Slot-Menge bleibt **unverändert** (nichts entfernt, nichts umsortiert), „meiden" ist ein
      überstimmbarer Hinweis. Markiert wird **nur heute** — eine Messung beschreibt die
      Vergangenheit, nicht nächsten Donnerstag. import-linter: nur `scheduling`+`mealplanner`
      dürfen `wearables` sehen, und nur über `api`.
      **Mealplan-Anbindung:** in 9-S7 bewusst aufgeschoben, mit dem Vorschlags-Slice aufgelöst
      (`GET /v1/mealplan/suggestion` ✅ 2026-07-27, read-only, ADR-0081 §9). Begründung damals: `suggest_slot` ist ein Schreibpfad in den
      geteilten Wochenplan — dort würde der Gesundheitszustand eines Mitglieds einen
      Haushalts-Datensatz bestimmen (ADR-0081 §9). Braucht eine persönliche, nicht schreibende
      Oberfläche.
      **9-S8 ✅** (2026-07-27): Web — Sektion auf `/profile` (mitglieds-privat, zugleich Ziel des
      Callback-Redirects): Consent-Checkboxen pro Datentyp, Verbinden als volle Navigation,
      Consent-PATCH mit der vollständigen Menge, zweistufiges Trennen mit benannter Folge,
      `needs_reauth` hervorgehoben, Betriebsfehler ruhig. **Die UI zeigt nie einen Messwert** —
      nur *ob* verbunden und *welche* Typen zugestimmt sind (per Test festgehalten);
      Consent-Picker axe-clean. 21 neue Web-Tests.
      Slice-Reihenfolge: ~~OAuth+Consent~~ → ~~Cron+Retention~~ → ~~Scheduling-Signal~~ →
      ~~Web~~ → ~~persönlicher Mealplan-Vorschlag~~ (`GET /v1/mealplan/suggestion`, read-only,
      ADR-0081 §9 — **gebaut**; was fehlt, ist nur die Oberfläche, s. „Endpunkte ohne Oberfläche").
      **Offen:** Oura-Feld-Mapping gegen die Live-API verifizieren. Betreiber-Handgriff: Oura-App registrieren, `CUSTODE_OURA_CLIENT_ID`/
      `_SECRET` setzen (interne Betriebsliste). **Das Oura-Feld-Mapping ist gegen
      die Live-API noch unverifiziert** — Korrektur gehört an den ersten echten Lauf.)
- 🔶 Google-CalDAV: Bearer-Auth-Fundament steht (`CaldavAuth`, `safe_request(bearer=…)` mit
      Origin-Lock für beide Credential-Formen). Der Google-Slice selbst ist **bewusst nicht
      begonnen**: ob Googles CalDAV-Endpunkt einen OAuth2-Bearer akzeptiert, ist die **Prämisse**
      des Slices und ohne registrierte App nicht verifizierbar — trifft sie nicht zu, ist es ein
      anderes Feature (REST-Adapter). Unblocker: Google-App registrieren + ein `curl`.
- 🎯 Nextcloud- & Google-Sync 2 Wochen stabil; Oura-Daten fließen nachweisbar
     ins Scheduling; ohne Wearable voll funktionsfähig.
     **Stand:** technisch fertig bis auf Google; der 🎯 hängt nur noch an Betriebs-Handgriffen
     (interne Betriebsliste, nicht im Repo).

## Phase 10 — Android-App
- ⬜ Kotlin/Compose, Room (Liste offline voll, Rest gecacht), WorkManager-Sync,
      generierter API-Client, FCM (Wecksignal), Health Connect (Consent je Typ)
- 🎯 Einkauf im Flugmodus komplett; Sync-Konflikt-Suite grün; Health-Connect-
     Daten im Scheduling; Play-Console-Health-Connect-Freigabe eingeholt.

## Phase 11 — Hardening + Recht → Release 0.1
- ⬜ ASVS-L2-**Selbstdurchgang** (`docs/security/`: Bedrohungsmodell-Vollversion, AuthZ-Matrix,
      Checkliste gegen den Code) + Fixes; DSFA fertig.
      **Der externe Pentest wandert nach Phase 12** (Entscheidung 2026-07-31): KONZEPT §8 und der
      Budgetposten in §13 verorten ihn zweimal „vor dem kommerziellen Launch", die Roadmap zog ihn
      hier vor. Bis dahin trägt der Selbstdurchgang; der Prüfer bekommt später ein Scope-Dokument
      statt einer Codebasis und sieht mehr fertigen Code.
- 🔶 Export (Nutzer + Haushalt) & Löschkaskade E2E; Backup-Restore-Probe;
      Lasttest; Runbooks
      **Export ✅** (2026-07-31, ADR-0083): `GET /v1/me/export` (jede Rolle, auch Kinder — das
      Recht gehört der Person) und `GET /v1/household/export` (nur admin) liefern ZIP mit
      `manifest.json`, `LIESMICH.txt`, `data/<tabelle>.json`, `attachments/<key>`. **Die
      Mandantengrenze ist die RLS, keine WHERE-Klausel** — gelesen wird auf der scoped session des
      Aufrufers, also bekommt ein Admin die Art.-9-Zeilen eines Mitbewohners **nicht** (ADR-0081,
      N-2; der Kerntest ist Admin-gegen-Mitglied). Alle 54 Tabellen sind klassifiziert (42
      exportiert, 12 ausgeschlossen mit Begründung), und **zwei** Gates halten das: eines über
      `Base.metadata` (schnell) und eines gegen die echte Datenbank (`information_schema`), weil
      das ORM nur eine Teilmenge des Schemas kennt — `tenancy_probe` und `guides.search_tsv` waren
      genau dort versteckt. Redaktion ist eine Denylist mit Namens-Gate, der zurückgehaltene Wert
      bleibt als `"<redaktiert>"` **sichtbar**. `shared` muss **ausdrücklich** gesetzt werden: wer
      eine neue Tabelle ohne Nachdenken aufnimmt, bekommt zu wenig Daten, nie die einer fremden
      Person. Bewusst synchron; die Grenze greift beim **Sammeln** (200 000 Zeilen,
      `export_too_large`, 413) statt am fertigen Archiv — eine Absage darf nicht mehr kosten als
      die Antwort. **Web:** eine Sektion auf `/profile` mit
      beiden Knöpfen (Blob über den generierten Client, damit Cookie/CSRF/401-Refresh gelten;
      Mutation statt Query, sonst legte ein Fokuswechsel still eine zweite Kopie in den
      Download-Ordner; Dateiname aus `Content-Disposition`, aber gefiltert) — sie nennt auch, was
      **fehlt**. 55 Backend- + 20 Web-Tests, axe-clean, DE+EN; keine Migration, kein
      Betreiber-Handgriff. Vorgezogen, weil die Klassifizierung zugleich die Vorarbeit der
      Löschkaskade ist.
      **11-S1a ✅** (2026-07-31): **der Austritt beendet den Zugang**. KONZEPT §5.1 ist als
      verbindlich markiert und war zu 0 % gebaut — `remove_member` setzte ein Tombstone, emittierte
      `member.left`, und das Ereignis hatte keinen Fach-Handler. Geschlossen: der **ICS-Feed-Token**
      (unauthentifiziert, an nichts gebunden, kein Ablauf — ein entferntes Mitglied las den
      Haushaltskalender **dauerhaft** weiter), die **Sitzung** (`Principal` kommt aus dem opaken
      Token, nicht aus der DB → bis zu 15 min voller Zugriff), das **CalDAV-Abo** und die
      **Wearable-Verbindung** (Art.-9-Daten ohne Rechtsgrundlage; hart gelöscht, Consent-Ledger
      bleibt als Nachweis). Handler am Composition Root (ADR-0039), idempotent, negativprobiert.
      **11-S1b ✅** (2026-07-31): der Ökonomie-Teil. Restpunkte verfallen als **Buchung**
      (`ref_type='member_exit'`), nicht als Löschung — der Ledger ist doppelte Buchführung, Salden
      sind Summen, ein Löschen veränderte die Salden anderer. Davor: offene Verkäufe zurückziehen,
      angenommene Käufe **rückabwickeln** (dafür entstand `revert_listing`; der Zustand `reverted`
      stand seit 0028 im CHECK, ein Codepfad dorthin existierte nie). Zugewiesene offene Aufgaben
      gehen in den Pool zurück. Die **Reihenfolge** ist die eigentliche Aussage und steht in
      `app/member_exit.py`. **Offen aus §5.1:** nur noch die Vault-Rotation (eigener ADR nötig).
      **11-S1c ✅** (2026-08-01): **Kontolöschung beantragen.** `DELETE /v1/auth/account` +
      `GET …/deletion-blockers`. Zweistufig — sofort gesperrt (`users.deleted_at`, bis dahin eine
      **tote Spalte**; alle fünf Anmeldetüren weisen ab), endgültig erst nach der Karenz. Der
      **Austritt aus allen Haushalten geschieht dagegen sofort**: die erste Fassung emittierte kein
      `member.left`, womit für ein selbst gelöschtes Konto **keiner** der vier 11-S1a-Handler lief
      und der unauthentifizierte ICS-Token gültig blieb. Die Karenz schützt davor, sein *Konto*
      wegzuwerfen; sie ist kein Grund, dreißig Tage weiter Art.-9-Daten abzuholen.
      **Slice A ✅** (2026-08-01): **Mitgliederverwaltung im Web + Selbst-Austritt.** Die 409
      `last_admin` nannte einen Ausweg („übertrage zuerst die Admin-Rolle"), für den es **keine
      Oberfläche gab** — `PATCH`/`DELETE` auf `/household/members/{id}` trägt das Backend seit
      Phase 1, das Web rief sie nie auf. Neu: `POST /v1/household/leave` (jede Rolle,
      `CurrentPrincipal`), die Mitgliederliste auf `/account`, die Gefahrenzone auf `/profile`, die
      die Blocker **vor** dem Knopf abfragt, und der von KONZEPT §5.1 verlangte
      **Vault-Warnhinweis** — der die Wahrheit sagt (keine Rotation, wer das Passwort kennt, liest
      Altbestände weiter) statt der Zusage. Dritter Abweisungsgrund `sole_member`, den es nur beim
      Austritt gibt; der bewusste Unterschied zur Kontolöschung ist durch einen eigenen Test
      festgenagelt. Nachgeholt: drei fehlende AuthZ-Matrix-Zeilen.
      **11-S1d (Klassifizierung) ✅** (2026-08-01): `app/deletion_policy.py` beantwortet je Spalte,
      was aus ihren Zeilen wird. Der Befund dahinter: von **31** personenbezogenen Spalten im
      **echten** Schema haben **vier** einen FK auf `users` — drei kaskadieren,
      `memberships.user_id` blockiert. Die Löschkaskade kann sich auf keine einzige FK-Regel
      verlassen. Weil die `users`-Zeile anonymisiert **stehen bleibt** (KONZEPT §5.1), bleiben alle
      Verweise gültig; es genügen `delete` / `keep` / `operator`. Gate gegen die echte Datenbank
      (nicht `Base.metadata` — das kennt 29 Spalten weniger), negativprobiert.
      **11-S1d (Purge) ✅** (2026-08-01): der Job läuft (Cron 03:30, `users.purged_at`,
      `docs/LOESCHKONZEPT.md`). Die Rechteprüfung vorweg fand, dass **4 von 14** Purge-Tabellen ein
      DELETE hatten und vier gar keine Policy — ohne Migration 0072 wäre er jede Nacht stumm
      gestorben wie der Reaper. Das Gate der Vorstufe war zudem nicht so breit wie behauptet: neun
      Personenbezüge (`author_id`, `from_id`, `cook_id`, `contact_id` …) fielen durch. Jetzt muss
      **jede** `_id`-Spalte eingeordnet sein. Der Export-nach-Löschung-Test hält beide Listen
      gegeneinander.
      **11-S1e (Auflösung, Phase 1) ✅** (2026-08-01, ADR-0085): ein Admin kann seinen Haushalt
      auflösen — die Operation, die `sole_member` und `only_children` auflöst. Alle Zugänge enden
      sofort, Kinder-Konten werden mit vorgemerkt, die Ökonomie läuft über **alle** Mitglieder in
      fester Reihenfolge (eigenes Ereignis, weil `revert_listing` den Verkäufer kreditiert und
      dessen Saldo sonst schon verfallen sein kann). Vier Eintrittstüren lesen jetzt
      `households.deleted_at`. KONZEPT §5.1 + Leitplanke 6 wurden **vorher** geändert (E9): die
      Auflösung ist **nicht** wiederherstellbar, die 30 Tage sind eine Purge-Verzögerung.
      **11-S1f ✅** (2026-08-02, ADR-0086): **Art. 17 ist zu Ende gebaut.** Cron um 04:00 (nach dem
      Konto-Purge um 03:30) räumt aufgelöste Haushalte nach der Karenz aus. Menge zur Laufzeit aus
      dem Katalog abgeleitet, Reihenfolge topologisch aus `pg_constraint`, gelöscht als
      `custode_app` unter RLS — das DELETE nennt den Haushalt nicht, die Policy tut es. Der
      Durchgang läuft **je Mitglied**, statt die zwei mitglieds-gescopten Tabellen zu benennen;
      negativprobiert (auf ein Mitglied verkürzt gehen zwei Tests rot). `points_ledger` und die
      `households`-Zeile fallen, `audit_log` und `consents` bleiben — beide ohnehin DB-seitig
      gesperrt, mit eigenem Test auf `42501`. 14 Tests, vier Gates gegen die echte Datenbank.
      **Keine Migration, kein neues Recht, kein Betreiber-Handgriff.**
      Die Zahlen, auf denen das steht (2026-08-02, gegen eine frisch migrierte Datenbank
      gemessen):
      · **41 Tabellen** tragen `household_id`, **0** Fremdschlüssel zeigen auf `households.id`
      (bestätigt, nicht übernommen).
      · **9 FK-Kanten** zwischen diesen Tabellen; **4 kaskadieren**
      (`calendar_events→external_calendar_subscriptions`, `letter_reads→letters`,
      `meal_slots→meal_plans`, `note_versions→notes`), **5 stehen auf `NO ACTION`** und binden die
      Reihenfolge auch innerhalb einer Transaktion: `task_instances→task_templates→rooms`,
      `recipe_ingredients→recipes`, `shopping_items→shopping_lists`, `redemptions→rewards`.
      · **Trockenlauf als `custode_app` unter gesetztem Scope: 40 von 42 Zielen** (41 Tabellen +
      `households`-Zeile) lassen ein `DELETE` zu. Genau zwei scheitern mit `42501` — `audit_log`
      und `consents` —, und beide sollen ohnehin bleiben. **Es braucht damit keine
      Grant-Migration**, anders als beim Konto-Purge (0072). Der Trockenlauf gehört trotzdem als
      Gate in den Slice: Postgres prüft Rechte beim *Planen*, nicht beim Treffer.
      · **Zwei Tabellen tragen eine mitglieds-gescopte Policy** (`wearable_connections`,
      `wearable_daily`, ADR-0081). Ein Lauf unter einer einzigen Identität meldet dort erfolgreich
      „0 Zeilen" und lässt fremde Art.-9-Daten liegen. **So umgesetzt: diese zwei werden nicht
      benannt** (eine Repräsentation, die beim nächsten member-gescopten Modul veraltet), sondern
      der ganze Durchlauf wiederholt sich **je Mitglied** — dann entscheidet die Datenbank, was jede
      Sitzung sehen darf. Kosten: ein paar Dutzend wirkungslose Anweisungen.
      · **Zwei Einordnungen entschieden (Betreiber, 2026-08-02):** `points_ledger` wird
      **gelöscht** — „append-only" ist eine Regel über *Korrekturen* im lebenden Ledger, nicht über
      das Ende des Mandanten; 11-S1b lässt Restpunkte bewusst als *Buchung* verfallen, damit die
      Salden der anderen stimmen, und nach der Auflösung gibt es keine Salden mehr, die stimmen
      müssten. Die `households`-Zeile wird **ebenfalls gelöscht**; ihr Fehlen *ist* die Markierung
      „ausgeräumt", also braucht es **kein** `households.purged_at` und keine Migration.
      `audit_log.household_id` zeigt danach ins Leere — von ADR-0084 ausdrücklich vorgesehen.
      **Offen aus §5.1:** weiterhin nur die Vault-Rotation.
- ⬜ **Phase 11 — Hardening und Recht: läuft;** die offenen Einheiten werden als
      GitHub-Issues geführt, sobald sie behoben sind.
- ✅ **11-S1g — `refresh` prüft die Mitgliedschaft** (2026-08-02, BUGLOG). `POST /v1/auth/refresh`
      las (Haushalt, Rolle) aus **Redis** (`get_active_household`, TTL = Refresh-Lebensdauer) und
      prüfte weder `households.deleted_at` noch eine lebende Mitgliedschaft noch die aktuelle
      Rolle. Zwei Folgen, und die zweite brauchte kein Rennen: (a) wer sich im Fenster zwischen
      Sitzungs-Widerruf und Commit einer Auflösung neu anmeldet, hielt eine Sitzung, die in keinem
      `families`-Satz steht und 30 Tage weiterrotierte; (b) ein per `change_role` herabgestufter
      Admin behielt seine Admin-Rechte **unbefristet** — `change_role` widerruft, anders als
      `remove_member`, keine Sitzungen, und die Rotation schrieb die alte Rolle fort.
      **Gebaut:** `resolve_refresh_scope` leitet Haushalt und Rolle je Rotation über dasselbe
      `get_active_role` ab, das der Haushaltswechsel benutzt — keine zweite Fassung der Bedingung.
      Aus dem Merkzettel wird nur noch der **Haushalt gelesen** (die Rolle steht weiterhin darin,
      wird aber verworfen — `household_id, _ = cached`), und er wird bei Scope-Verlust geräumt; **kein**
      Auto-Scope beim Rotieren (das gehört zur Anmeldung, #132). Dazu entwertet `change_role` die
      **Access-Tokens** der betroffenen Person — nicht ihre Sitzungen, sie bleibt Mitglied —, damit
      die neue Rolle in einer Anfrage greift statt in fünfzehn Minuten.
      Acht Regressionstests, jeder mit dem Vorher davor, zweistufig negativprobiert.
- ✅ **Der stille 401-Replay im Web wiederholt jetzt auch Schreibzugriffe** (2026-08-03, 11-B2, BUGLOG). Vorher: er wiederholte nur GETs (benannt beim adversarialen Durchgang zu
      11-S1g). `web/src/auth/client.ts:100` ruft `request.clone()`, nachdem `fetch` den Body bereits
      verbraucht hat — für POST/PATCH/DELETE mit Body wirft das, der `catch` reicht die ursprüngliche
      401 durch, und der Nutzer sieht einen Fehler statt seiner Aktion. Der Kommentar in derselben
      Zeile sagt das offen; es ist also kein Versehen, aber auch keine Entscheidung, die je jemand
      gegen ihre Kosten geprüft hat. **Es feuert heute schon bei jedem 15-Minuten-Ablauf** — die
      erste Schreibaktion nach einer Pause schlägt einmal fehl und funktioniert beim zweiten Versuch.
      11-S1g macht es zusätzlich *deterministisch*: wessen Rolle gerade geändert wurde, dessen
      nächster Schreib-Request trifft es sicher. Der Fix gehört in den Client (Body vor dem ersten
      Senden puffern, damit der Replay ihn hat), nicht in den Auth-Pfad, und berührt jeden
      Schreibweg — deshalb ein eigener Slice. Zweitbefund derselben Stelle: `EventSource`
      (`web/src/realtime/stream.ts:18`) geht am Interceptor vorbei, der Live-Kanal bleibt nach einer
      Entwertung stumm, bis ein anderer `fetch` die Rotation auslöst.
      **Gebaut:** der Body wird im **Request**-Interceptor geklont — dem letzten Moment, in dem er
      unversehrt ist — und ueber eine `WeakMap` an den Response-Interceptor gereicht. Dazu zwei
      Nebenbefunde derselben Datei: die Pfad-Ausnahmen matchten per **Substring**, womit `/login`
      auch die authentifizierte Route `/v1/auth/login-events` traf (Sicherheits-Aktivitaet fiel
      nach 15 min stumm aus) — jetzt Segment-Vergleich mit vollen Pfaden; und der SSE-Kanal
      bekommt einen eigenen Reconnect samt Rotation, weil der Browser bei einer Nicht-2xx-Antwort
      **endgueltig** aufgibt. Ein *transienter* Abbruch bleibt bewusst dem Browser ueberlassen.
      Tests: auth-client 4 -> 9, realtime-stream 4 -> 9.
- ✅ **`logout` ist symmetrisch** (2026-08-03, 11-B3, BUGLOG). Vorher: `logout` ohne gültiges Access-Cookie räumte Redis nicht (Bestand, benannt beim
      adversarialen Durchgang zu 11-S1g). `POST /v1/auth/logout` ruft `revoke_access_family` nur,
      wenn `load_access` Claims liefert; fehlt das Access-Cookie oder ist der Redis-Eintrag
      abgelaufen, bleiben `active_household:<family>` (30 Tage) und etwaige Geschwister-Tokens der
      Familie stehen, während `auth_sessions.revoked_at` gesetzt wird. Der Merkzettel ist seit
      11-S1g **inert** (sein einziger Leser verlangt eine nicht widerrufene Sitzung), und
      Access-Cookie und Redis-Eintrag tragen dieselbe TTL — der Fall ist damit schmal, aber der
      Spiegelfall ist es nicht: Logout **mit** Access-, **ohne** Refresh-Cookie verbrennt Redis und
      lässt `revoked_at` auf NULL, die Sitzung lebt also weiter. Beide Zweige gehören
      zusammengeführt: **eine** Funktion, die Sitzung *und* Tokens beendet, statt zweier Pfade, die
      sich je nach vorhandenem Cookie unterschiedlich weit erstrecken.
      **Gebaut:** genau das — `service.logout` leitet die `family_id` aus dem ab, was ankommt
      (Nachschlag zum Refresh-Token, sonst Access-Claims) und wirkt unbedingt auf **beide**
      Speicher; erst Postgres, dann Redis, damit ein Fehler Richtung *weniger* Zugriff fehlt.
      Zwei neue Tests decken die zwei asymmetrischen Cookie-Kombinationen — vorher waren nur die
      beiden symmetrischen geprüft, was in der Testliste vollständig aussah.
- ✅ **Der Fehlerkatalog ist eingeholt und gegen den Code genagelt** (2026-08-03, 11-A2). Vorher hinkte er um **59** Slugs hinterher.
      `docs/errors.md` sagt „neue Codes werden hier ergänzt **bevor** sie im Code verwendet werden"
      und bricht diese Regel selbst: `insufficient_funds`, `out_of_stock`, `cooldown_active`,
      `not_your_task`, `sync_unknown_entity`, `import_url_blocked`, `resync_required` und viele
      mehr fehlen; für `tasks`, `economy`, `calendar`, `marketplace`, `recipes`, `shopping`,
      `mealplanner`, `vault` und `guides` gibt es gar keinen Abschnitt. Das ist keine Kosmetik:
      die DoD verlangt für jeden nutzerseitigen Fehler einen Katalogeintrag, und die
      Web-Fehlertexte hängen an denselben Slugs.
      **Gebaut:** alle 97 erzeugbaren Slugs dokumentiert, nach Modul gegliedert, mit den neun
      fehlenden Abschnitten. Sechs **Geister-Einträge** entfernt bzw. richtiggestellt
      (`ssrf_blocked`, `payload_too_large`, `rate_limited`, `conflict_version`,
      `idempotency_replay` — vier davon hatten einen real existierenden, aber **anders benannten**
      Zwilling im Code; wer nach ihnen suchte, fand nichts).
      **Das Gate** (`tests/test_error_catalogue.py`) haelt beide Richtungen: Slug ohne Eintrag rot,
      Eintrag ohne Erzeuger rot, und ein nicht-literales `slug=` muss ausdruecklich quittiert werden.
      Es fand beim ersten Lauf eine Luecke **in sich selbst**: die erste Fassung sah nur
      `ProblemException(...)` und uebersah `TokenReuseError`, das seinen Slug per
      `super().__init__` setzt — ein Muster am Namen statt an der Sache.
      **Dazu der Handler, den es nicht gab:** ein unerwarteter Fehler verliess den Server als
      `text/plain` „Internal Server Error" — ohne `type`, ohne `reference`, nicht einmal
      `problem+json`, obwohl der Katalog das zweimal zusagt und ARCHITECTURE §12 die
      Fuenf-Minuten-Auffindbarkeit darauf baut. Jetzt `problem+json` mit Referenzcode (im Body
      **und** im Header, weil ein `Exception`-Handler ausserhalb der Kontext-Middleware laeuft),
      ohne Ausnahmetyp und ohne Meldung — die Einzelheiten stehen im Log.
- ✅ **Test-Suite: das stille Überspringen** (2026-08-03, 11-A1). **75** Testdateien starteten je
      einen eigenen `PostgresContainer` und endeten auf `pytest.skip("Docker/Postgres not
      available")`. Ohne Docker meldete der Lauf `563 skipped, 374 passed` und **Exit 0** — die
      komplette RLS-, HTTP- und Export-Abdeckung verschwand, und der Job wurde grün. Dieselbe Lehre
      wie beim Reaper („ein Job, der nur bei Wirkung loggt, ist im Fehlerfall stumm"), nur auf
      Suite-Ebene.
      **Gebaut:** ein Container je Session (`backend/tests/dbfixture.py`), die vier DB-Rollen
      einmal angelegt (Rollen sind in Postgres clusterweit), die 72 Migrationen einmal in eine
      **Template-Datenbank**, und je Testmodul eine frische Datenbank per `CREATE DATABASE …
      TEMPLATE` — eine Dateikopie statt eines Migrationslaufs. Die Isolation ist unverändert: eine
      eigene Datenbank ist mindestens so scharf wie ein eigener Container.
      **Das Gate** sitzt in `pytest_sessionfinish` (`backend/tests/conftest.py`): ein Lauf, in dem
      Tests wegen fehlender Infrastruktur übersprungen wurden, endet rot. Abschaltbar mit
      `CUSTODE_TESTS_ALLOW_SKIPPED_INFRA=1` — als Entscheidung, nicht als Default. Dazu `-ra` in
      `addopts`: mit dem blossen `-q` stand nicht einmal der **Grund** eines Skips im Log.
      **Zahlen (Stand des Slice):** 989 Tests, **0** Skips, **5:09** statt ~11 min. Und der Nebengewinn, der mit
      jedem Slice wächst: eine neue Migration verlängert die CI nicht mehr um das 75-fache ihrer
      Laufzeit, sondern um ihre Laufzeit.
      **Was das Gate sofort gefunden hat** (und was den Punkt rechtfertigt): `test_deletion_policy.py`
      meldete einen kaputten Fixture-Umbau sieben Tests lang als „Docker/Postgres not available" —
      genau die Tarnung, wegen der jeder dieser Skips einzeln unverdächtig aussah. Ein
      `except Exception`, das alles „kein Docker" nennt, ist eine Repräsentation statt eines Begriffs.
- 🎯 Privater Vollbetrieb + Closed Beta in Wellen; alle SLOs gehalten.

## Phase 12 — Bug-Hunts/Refactors → Release 0.2 (kommerziell)
- ⬜ Retention messen; Abo-/Zahlungsintegration und Betreiber-Konsole v2
      (Details nicht Teil der Veröffentlichung)
- ⬜ **Externer Pentest + Fixes** (aus Phase 11 hierher, KONZEPT §8/§13: „vor dem kommerziellen
      Launch"); Abnahme: kein offener Befund ≥ hoch
- ⬜ Migration Beta-Server → Hetzner (Runbook geprobt); **SPF/DKIM/DMARC samt Wechsel auf eine eigene
      Versanddomain** (Entscheidung 2026-07-31: bewusst hier statt sofort — Risiko benannt,
      interne Betriebsliste); Launch
- 🎯 Stabil im Dauerbetrieb; Kennzahlen der Betreiber-Konsole belastbar.

## Danach
Phase 13 Finanzen-Modul (§5.18) · Garmin-Cloud-Antrag · eigener CalDAV-Server ·
Kundenkarten-Wallet · iOS-Evaluierung (datengetrieben).
