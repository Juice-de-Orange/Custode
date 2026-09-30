# Architecture Decision Records (ADR)

Format: [`0000-template.md`](0000-template.md). Neue ADRs sind eigene Dateien
`NNNN-kurztitel.md` und werden hier eingetragen. Eine getroffene Entscheidung
wird nicht still geändert — sie wird durch einen neuen ADR **revidiert** oder
**abgelöst** (Prinzip E9).

## Beschlossene ADRs 001–015 (Register in der Architektur)

ADR 001–015 sind im **Register** [`../../KONFIG/ARCHITECTURE.md` §17](../../KONFIG/ARCHITECTURE.md)
dokumentiert und werden bewusst **nicht** als Einzeldateien dupliziert
(Single Source, kein Drift — ADR-0018). Kurzüberblick:

| ADR | Entscheidung | Status |
|---|---|---|
| 001 | Modular Monolith statt Microservices | beschlossen |
| 002 | SSE-Invalidation-Hints statt WebSocket | beschlossen |
| 003 | LWW pro Feldgruppe statt CRDT | beschlossen |
| 004 | UUIDv7 als Primärschlüssel | beschlossen |
| 005 | Postgres FTS zuerst, Meilisearch hinter Port | beschlossen |
| 006 | Lingui/ICU, i18n ab Tag 1 — DE + EN | beschlossen |
| 007 | Radix-Primitives + Tailwind-Tokens als Design-System-Basis | beschlossen |
| 008 | taskiq als Job-System (arq maintenance-only) | revidiert 10.06.2026 |
| 009 | RFC-9457-Fehlerformat | beschlossen |
| 010 | Merchant of Record (Paddle) für Payments | beschlossen |
| 011 | Idempotency-Key auf allen POSTs | beschlossen |
| 012 | FCM nur als Wecksignal ohne Inhalte | beschlossen |
| 013 | Postgres 18 | beschlossen |
| 014 | OpenTelemetry-SDK ab Tag 1, OTLP → Sentry | beschlossen |
| 015 | Backoffice nur auf Aggregat-Views, nie Fachdaten | beschlossen |

## ADRs ab 016 (Einzeldateien hier)

| ADR | Entscheidung | Status |
|---|---|---|
| [016](0016-python-tooling-uv.md) | `uv` als Python-Environment/Dependency-Manager | beschlossen |
| [017](0017-web-package-manager-npm.md) | `npm` als Web-Paketmanager | beschlossen |
| [018](0018-repo-layout-and-doc-canon.md) | Monorepo-Layout & Doku-Kanonik (KONFIG/ vs docs/) | beschlossen |
| [019](0019-github-and-actions.md) | GitHub + GitHub Actions statt GitLab CE; Deploy auf den Produktionsserver | beschlossen |
| [020](0020-production-deployment.md) | Produktions-Deployment (Compose-Härtung statt dev-Defaults) | beschlossen |
| [021](0021-access-token-cookies-csrf.md) | Opaque Redis-Access-Token, Cookie-Sessions & CSRF | beschlossen |
| [022](0022-totp-2fa.md) | TOTP-2FA (RFC 6238, einstufiger Login, Secret RLS-geschützt) | beschlossen |
| [023](0023-passkeys-webauthn.md) | Passkeys (WebAuthn) — py-webauthn, request-derived RP | beschlossen |
| [024](0024-web-hosting-caddy-front.md) | Web-Auslieferung via Caddy-Front (eine Origin) | beschlossen |
| [025](0025-auth-audit-user-scoped.md) | Auth-Audit ist user-scoped, nicht tenant-scoped | beschlossen |
| [026](0026-qr-code-totp-setup.md) | QR-Code für TOTP-Setup (clientseitig, `qrcode.react`) | beschlossen |
| [027](0027-email-smtp-mailbox-org.md) | E-Mail-Versand via mailbox.org SMTP (aiosmtplib) | beschlossen |
| [028](0028-child-pin-login.md) | Kinder-Accounts — Username + PIN-Login (Argon2id, ratenlimitiert) | beschlossen |
| [029](0029-recipes-patch-if-match.md) | Rezepte via PATCH + If-Match (Sync-Batch erst ab Phase 3) | beschlossen |
| [030](0030-ssrf-safe-fetch.md) | SSRF-Guard für ausgehende URL-Abrufe (`kernel/fetch.py`) | beschlossen |
| [031](0031-reference-data-tables.md) | Referenz-/Stammdaten als globale Tabellen (RLS-Ausnahme) | beschlossen |
| [032](0032-sync-batch-lww-field-groups.md) | Sync-Batch — LWW pro Feldgruppe (Offline-Schreibpfad) | beschlossen |
| [033](0033-blob-storage-photos.md) | Blob-Storage-Adapter + Foto-Normalisierung | beschlossen |
| [034](0034-tasks-write-path-and-state-machine.md) | Haushaltsaufgaben — Schreibpfad PATCH + If-Match & Erledigen-Zustandsmaschine | beschlossen |
| [035](0035-points-ledger-and-economy-api.md) | Punkte-Ledger — Modell & synchrone Gutschrift via economy.api | beschlossen |
| [036](0036-task-value-decay.md) | Wert-Verfall überfälliger Aufgaben — Defaults & Anwendung bei Erledigung | beschlossen |
| [037](0037-marketplace-escrow.md) | Marketplace — Escrow über das Ledger, einseitige Modulgrenzen, expliziter Settle | beschlossen |
| [038](0038-capture-apply-via-sync-batch.md) | Capture — Vorschläge serverseitig über die Ziel-Modul-APIs anwenden | beschlossen |
| [039](0039-module-outbox-handlers-at-composition-root.md) | Modul-Outbox-Handler mit Domänen-Seiteneffekt am Composition-Root registrieren | beschlossen |
| [040](0040-calendar-layer-visibility.md) | Kalender — Layer-Sichtbarkeit query-seitig, RLS bleibt tenant-only | beschlossen |
| [041](0041-rrule-engine-python-dateutil.md) | RRULE-Engine — `python-dateutil` statt Eigenbau | beschlossen |
| [042](0042-calendar-ics-secret-feed.md) | Kalender-ICS-Feed — unauthentifizierter Secret-Token, read-only, maint-Lookup | beschlossen |
| [043](0043-occurrence-exceptions-set-semantics.md) | Einzel-Occurrence-Ausnahmen als EXDATE-Menge ohne If-Match | beschlossen |
| [044](0044-ics-import-file-upload.md) | ICS-Import als Datei-Upload (kein URL-Fetch), Dedup über UID | beschlossen |
| [045](0045-weather-provider-adapter.md) | Wetter: Provider-Adapter mit Null-Adapter, eigenes Standort-Modell, Open-Meteo fix | beschlossen |
| [046](0046-scheduling-engine-read-only-slots.md) | Scheduling-Engine: read-only Slot-Vorschläge über die calendar.api-Naht | beschlossen |
| [047](0047-dst-correct-recurrence-tzid.md) | DST-korrekte Serien: Verankerung in der Event-Zeitzone (`tzid`) | beschlossen |
| [048](0048-move-occurrence-overrides.md) | Einzel-Occurrence verschieben: Overrides als JSONB-Map in der Master-Zeile | beschlossen |
| [049](0049-task-instance-room-heatmap-action.md) | Heatmap als Aktionsfläche: direktes `task_instances.room_id` | beschlossen |
| [050](0050-mealplanner-week-model.md) | Mealplanner: Wochen-Datenmodell + Rezept über recipes.api | beschlossen |
| [051](0051-recipe-cooked-history-via-mealplanner.md) | „Zuletzt gekocht"-Historie: synchron via recipes.api + `mealplan.cooked`-Event | beschlossen |
| [052](0052-mealplan-auto-suggest-least-recently-cooked.md) | Auto-Vorschlag („neu würfeln"): least-recently-cooked als reine Funktion | beschlossen |
| [053](0053-mealplan-cook-task-via-tasks-api.md) | Koch-Task aus einem Mealplan-Slot: synchron via tasks.api (S-03) | beschlossen |
| [054](0054-mealplan-absence-hint-via-calendar-api.md) | Abwesenheits-Hinweis im Wochenplan: read-only via calendar.api (S-01) | beschlossen |
| [055](0055-mealplan-prep-task-leadtime-heuristic.md) | Vorbereitungs-Task am Vortag: Lead-Time-Heuristik + tasks.api (S-02) | beschlossen |
| [056](0056-mealplan-week-nutrition-summary.md) | Wochen-Nährwert-Übersicht: Aggregation über recipes.api.recipe_macros | beschlossen |
| [057](0057-mealplan-nutrition-aware-fill.md) | Nährwert-bewusstes „Woche füllen": closest-to-target Auswahl | beschlossen |
| [058](0058-mealplan-exclusion-tag-filter.md) | Allergie-/Ausschluss-Filter beim Auto-Füllen: Tag-basiert | beschlossen |
| [059](0059-notes-module-foundation.md) | `notes`-Modul: manuelles Fundament (online-first, PATCH + If-Match) | beschlossen |
| [060](0060-note-version-history.md) | Notiz-Versions-Historie: Snapshot-vor-Edit, letzte 5 | beschlossen |
| [061](0061-note-convert-to-task.md) | Notiz „Konvertieren-zu Aufgabe": synchron via tasks.api | beschlossen |
| [062](0062-messaging-letters-read-receipts.md) | `messaging`-Modul (Briefe): Gelesen-Status als eigene Tabelle | beschlossen |
| [063](0063-letter-convert-to-task.md) | Brief „Kümmerst du dich?" → Aufgabe: synchron via tasks.api | beschlossen |
| [064](0064-guides-module-german-fts.md) | `guides`-Modul (Anleitungen): deutsche Volltextsuche via GENERATED tsvector | beschlossen |
| [065](0065-comments-generic-object-thread.md) | `comments`-Modul: generische Threads via (object_type, object_id) | beschlossen |
| [066](0066-object-links-generic.md) | `object_links`: generische, richtungsunabhängige Verknüpfungen | beschlossen |
| [067](0067-vault-client-side-encryption.md) | Vault: clientseitige E2E-Verschlüsselung, Server nur Ciphertext | beschlossen |
| [068](0068-capture-llm-enrichment.md) | Zuruf: optionale LLM-Anreicherung (Ollama) als Graceful Enhancement | beschlossen |
| [069](0069-guide-attachments.md) | Anleitungen: Datei-Anhänge (Bytes im Blob-Storage, Metadaten in der DB) | beschlossen |
| [070](0070-weekly-digest-fanout.md) | Wochen-Digest: haushaltsübergreifender E-Mail-Fan-out unter der maint-Rolle | beschlossen |
| [071](0071-ops-aggregate-views.md) | Betreiber-Konsole: Aggregat-Views + DB-Rollen-Trennung (Fundament) | beschlossen |
| [072](0072-operator-auth-stack.md) | Betreiber-Konsole: eigener Operator-Auth-Stack (Passwort + TOTP, Bearer-Session) | beschlossen |
| [073](0073-audit-log.md) | Append-only Audit-Log für Betreiber-Aktionen & Sicherheitsereignisse | beschlossen |
| [074](0074-ops-frontend-bundle.md) | Betreiber-Konsole-Frontend: eigenes Bundle/Subdomain + Bearer-Client | beschlossen |
| [075](0075-design-language-kino-ruhe.md) | Designsprache „Kino-Ruhe" (Evolution der „Ruhigen Moderne": kinematisch, Silhouetten-Szenen, Dark-Mode) | beschlossen |
| [076](0076-feedback-issue-forwarding.md) | Feedback → Issue-Tracker: Best-Effort-Weiterleitung als Graceful Enhancement (Null-Adapter) | beschlossen |
| [077](0077-server-side-credential-encryption.md) | Server-seitige Credential-Verschlüsselung (`kernel/crypto`, Fernet, `CUSTODE_CRYPTO_KEY`) | beschlossen |
| [078](0078-pwa-install-und-service-worker.md) | PWA: Installierbarkeit + Service Worker (vite-plugin-pwa, Prompt-Update) | beschlossen |
| [079](0079-caldav-pull-sync.md) | CalDAV Pull-Sync: Spiegel-Modell (`subscription_id`), REPORT+defusedxml, Fail-Safes | beschlossen |
| [080](0080-caldav-write-back.md) | CalDAV Write-back: GET-modify-PUT mit Property-Erhalt, Remote-first, href-Guard | beschlossen |
| [081](0081-wearables-member-scoped-rls-und-oauth.md) | Wearables: mitglieds-gescopte RLS für Art.-9-Daten + OAuth-Fundament (Consent-Widerruf, unauth. Callback) | beschlossen |
| [082](0082-ics-feed-vtimezone.md) | ICS-Feed DST-korrekt: `DTSTART;TZID=` + gesampelte `VTIMEZONE`-Übergänge (revidiert 0047) | beschlossen |
| [083](0083-datenexport-betroffenenrechte.md) | Datenexport (Art. 15/20): RLS als Mandantengrenze, Klassifizierung aller Tabellen am Composition Root, Redaktions-Denylist mit CI-Gate | beschlossen |
| [084](0084-loeschung-vs-auditierbarkeit.md) | Löschung vs. Auditierbarkeit: `audit_log` wird pseudonymisiert, nicht gelöscht | beschlossen |
| [085](0085-haushaltsaufloesung.md) | Haushalts-Auflösung: Selbstbedienung des Admins, zweistufig, Mandantengrenze bleibt RLS | beschlossen |
| [086](0086-haushalts-purge-abgeleitete-menge.md) | Haushalts-Purge: Menge aus dem Katalog abgeleitet, Reihenfolge aus `pg_constraint`, Durchgang je Mitglied | beschlossen |
