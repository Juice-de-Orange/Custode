# CLAUDE.md — Modul `wearables`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Anbindung von Wearable-Clouds (KONZEPT §5.15), Phase 9. 9-S5 = OAuth-Fundament + Art.-9-Consent
+ Datenmodell; 9-S6 = Ingest-Cron + Retention; 9-S7 = Scheduling-Naht; 9-S8 = Web.

**Strikt optional (Leitplanke 7):** Jede abhängige Funktion hat einen gleichwertigen Basis-Pfad
ohne Wearable-Daten. Die Daten verfeinern nur — sie sind nie Voraussetzung.

## Grenzen (hart)
- Importiert **nur** `kernel/*` und `modules/accounts/api` (Consent-Ledger, Rollenprüfung,
  Feature-Flags) — nie accounts-Internas, nie ein anderes Modul. Kein Modul importiert
  `wearables` (Einbahnstraße, import-linter).

## Das Besondere: Gesundheitsdaten sind mitglieds-privat (ADR-0081)
- **Die RLS-Policy enthält `member_id`, nicht nur `household_id`.** Migration 0069,
  `member_isolation`. Ein Mitbewohner — **auch ein Admin** — liest DB-seitig 0 Zeilen. Das ist
  die Abweichung vom Hausmuster: bei `external_calendar_subscriptions` ist owner-only eine
  Service-Konvention, hier ist es die Datenbank (N-2, Art. 9 DSGVO).
- Die Rolle steht **bewusst nicht** im Prädikat: es gibt keine privilegierte Lesart.
- Der Service filtert trotzdem zusätzlich `member_id` — Defence in Depth und lesbare Absicht.
- **Cron-Konsequenz (9-S6):** Aufzählen unter `custode_maint` (`maint_all` ist SELECT-only),
  **schreiben immer** unter `scoped_session(household_id, user_id=member_id)`.

## Datenmodell (Migration 0069)
- `wearable_connections`: `member_id`, `provider ∈ {oura, garmin, healthconnect}`, `tokens_enc?`,
  `token_expires_at?`, `scopes[]`, `status ∈ {active, needs_reauth}`, `last_error?`,
  `last_sync_at?` (+ Mixin). Eindeutig über `(household_id, member_id, provider)`.
- `wearable_daily`: `day`, `sleep_score?`, `sleep_minutes?`, `readiness?`, `steps?`,
  `active_kcal?`, `rhr?`, `fetched_at`. Eindeutig über
  `(household_id, member_id, provider, day)`.
- **`CHECK (deleted_at IS NULL)` auf beiden:** Art. 9 verlangt echtes Löschen. Nie einen
  Soft-Delete einführen; nie in `_RETENTION_TABLES` aufnehmen.

## Consent pro Datentyp (KONZEPT §5.15/§11)
- Vokabular in `types.py`: `wearable_sleep|readiness|activity|heartrate` — **feiner** als Ouras
  Scopes (`daily` deckt drei davon ab). `scopes_for()` bildet die Vereinigung ab; gefiltert wird
  beim Ingest pro Typ.
- Der Ledger gehört `accounts`. **Nie `consents` direkt lesen/schreiben** — nur über
  `accounts.api.record_consents` / `effective_consents`.
- Widerruf = **neue Zeile** (`action='revoke'`, Migration 0068); der wirksame Stand ist ein Fold
  („letzte Zeile je Typ gewinnt"), nie ein Spaltenwert.
- Consent entsteht **im Callback, in derselben Transaktion wie die Verbindung** — nie beim
  Authorize (sonst Consent ohne Verbindung, wenn der Nutzer beim Provider abbricht).
- **Invariante: keine Verbindung ohne mindestens einen aktiven Consent.** Widerruf des letzten
  Typs löscht die Verbindung hart.
- Widerruf eines Typs nullt **sofort** dessen Spalten in `wearable_daily`.

## OAuth (ADR-0081)
- Authorization Code, vertraulicher Client (Betreiber registriert die App). Oura hat Personal
  Access Tokens im Dez 2025 abgeschaltet — **nie** einen PAT-Pfad bauen.
- `state`: nur SHA-256-Hash in Redis, TTL 10 min, **single-use**; trägt Mitglied + Haushalt +
  gewählte Typen. Der Callback vertraut aus der Query **nur** dem Code.
- Callback ist **formal unauthentifiziert** + `include_in_schema=False` und antwortet **302**,
  nie problem+json. **Formal unauthentifiziert heißt nicht blind:** er prüft
  (a) den single-use `state` — welcher Vorgang, mit welchen Consent-Typen — **und**
  (b) per `peek_access_user_id`, dass der **Browser** dem Initiator gehört. Ohne (b) landet der
  Consent eines Fremden in der eigenen Zeile (BUGLOG 2026-07-30). Fehlende Session = Ablehnung.
  Dazu die Rolle per `accounts.api.get_active_role` **erneut** prüfen (Rollenwechsel im Fenster).
- **Nie** einen state über zwei Redis-Kommandos verbrauchen — `GETDEL`, sonst ist „single-use"
  bei zwei gleichzeitigen Callbacks keins.
- `redirect_uri` kommt aus **einer** Funktion (`router._redirect_uri`) — Authorize und Exchange
  müssen byte-identisch senden.
- `tokens_enc` = **ein** SecretBox-Wert (`v1:`) über
  `{access_token, refresh_token, token_type, scopes}` (`tokens.py` = Format-Kontrakt).
  `token_expires_at` bleibt **außerhalb** im Klartext, damit der Cron per SQL filtern kann.
- Ver-/Entschlüsselung **nur im Service** (eine Stelle garantiert: Klartext wird nie persistiert).
- Refresh-Antworten **ersetzen** `tokens_enc` komplett (Provider rotieren Refresh-Tokens).

## Ingest + Retention (9-S6)
- **Zwei getrennte Cron-Jobs**, beide in `app/worker.py`: `ingest_wearables_job` (`20 4 * * *`,
  respektiert den Kill-Switch) und `reap_wearable_daily_job` (`40 3 * * *`, **läuft immer** —
  Daten müssen altern, auch wenn keine neuen kommen).
- **Reihenfolge je Verbindung ist nicht beliebig:** Rolle → Refresh → Fetch → Consent-Filter.
  Die Rollenprüfung steht **vor** jedem ausgehenden Request, damit eine Herabstufung auch den
  Verkehr stoppt, nicht nur die Speicherung. Ein herabgestuftes Mitglied verliert Verbindung
  **und** Daten.
- **Der Consent-Filter ist die eigentliche Durchsetzung**, nicht der OAuth-Scope: `daily` deckt
  drei Datentypen ab, also entscheidet erst `consented_values()`, was gespeichert wird.
  Nicht-zugestimmte Spalten werden **auf NULL gesetzt**, nicht ausgelassen — sonst überlebte
  der Wert eines zwischenzeitlich widerrufenen Typs.
- **Fenster:** `INGEST_WINDOW_DAYS = 3` — Provider finalisieren und korrigieren Nächte nachträglich.
  Upsert auf `(member, provider, day)`, nie Duplikate.
- **Refresh:** nur wenn der Token binnen 30 min abläuft. Erfolg **ersetzt** `tokens_enc` komplett.
  Abgelehnter Refresh → `status='needs_reauth'` und die Verbindung wird nicht mehr aufgezählt —
  **nie** jede Nacht erneut versuchen.
- **Retention:** eigener Job, weil der Tombstone-Reaper nach `deleted_at` purgt und diese Tabellen
  Tombstones verbieten. Achse ist das Alter des **Messtags**. `custode_maint` hat dafür DELETE
  **nur auf `wearable_daily`** (Migration 0070) — eine Verbindung ist kein Messwert.

## Graceful Enhancement
- Kein `CUSTODE_CRYPTO_KEY` → Authorize/Callback 503 `crypto_unconfigured`; **Lesen und Löschen
  laufen weiter**.
- Kill-Switch `CUSTODE_OURA_ENABLED` aus oder Credentials fehlen → `NullWearableOAuth`, die
  **wirft** (`wearables_disabled`, 503). Nie „neutral" eine URL ausgeben, die ins Leere führt.
- Haushalts-Flag `wearables` (Default **aus**) → 403 `feature_disabled` beim Verbinden;
  Lesen/Löschen bleiben offen.
- **Datenpfad:** `NullWearable` liefert einen **Blank** (`UNKNOWN_WEARABLE`), sie wirft *nicht* —
  anders als `NullWearableOAuth`. „Keine Werte" ist ein gewichtsloses Signal, jede abhängige
  Funktion hat einen Basis-Pfad. Ein Lauf mit Null-Adapter holt nichts und speichert nichts.

## Schnittstellen (HTTP)
- `GET /v1/wearables/connections` — eigene Verbindungen (fremde: 404, auch für Admins).
- `POST /v1/wearables/oura/authorize` (CSRF) — startet den Flow, liefert `authorize_url`.
- `GET /v1/wearables/oura/callback` — **unauth**, 302, nicht im Schema.
- `PATCH /v1/wearables/connections/{id}/consents` (CSRF) — Typen ersetzen; leer ⇒ trennt.
- `DELETE /v1/wearables/connections/{id}` (CSRF) — hart, kein Papierkorb.
- Alle **member/admin**; Kinder und Gäste 403 (Root-CLAUDE.md).

## Die Naht nach außen (9-S7, Synergie S-14)
- `api.recovery_signal(session, member_id, today) -> RecoverySignal(available, low_recovery,
  as_of)`. **Ein Boolean, nie ein Score** — ein roher Gesundheitswert über einer Modulgrenze
  *ist* das Gesundheitsdatum.
- **Nur die eigenen Daten:** die RLS liefert für jede fremde `member_id` nichts. **Nur die eigenen
  Vorschläge:** Konsumenten dürfen damit formen, was sie *diesem* Mitglied anbieten — sichtbar
  werden darf es für niemanden sonst.
- **Nur `scheduling` + `mealplanner`** dürfen `wearables` importieren (import-linter), und auch
  die nur über `api`. Ein weiterer Konsument braucht eine bewusste Kontrakt-Änderung.
- **Zeitlich ehrlich:** Wearable-Daten beschreiben die Vergangenheit. Die Naht sagt „gerade
  erschöpft", nie „Donnerstag wird anstrengend"; Konsumenten markieren **nur heute**. Lesungen
  älter als `MAX_READING_AGE_DAYS` sind kein Signal.
- **Nie an einen Schreibpfad hängen, der geteilten Zustand erzeugt.** `mealplanner.suggest_slot`
  schreibt via `set_slot` in den Haushalts-Wochenplan und bleibt deshalb **signalfrei**; das
  Signal hängt am **nicht schreibenden** `GET /v1/mealplan/suggestion` (ADR-0081 §9). Wer eine
  dritte Naht baut, prüft zuerst: schreibt der Pfad in etwas Geteiltes?

## Events
- **publiziert:** — · **abonniert:** `member.left` (11-S1a).
- **Publizieren bleibt ausgeschlossen.** Der SSE-Fan-out ist haushaltsweit; ein
  `connection.created`-Hint würde Mitbewohnern verraten, dass jemand ein Wearable verbunden hat
  (N-2). Gilt auch für `wearable.daily_ingested`.
- **Abonnieren ist etwas anderes und erlaubt:** wer zuhört, verrät nichts. `handlers.py` trennt
  bei `member.left` jede Verbindung der Person und löscht ihre Daten **hart** — die Einwilligung
  galt für DIESEN Haushalt, mit der Mitgliedschaft endet die Rechtsgrundlage. Der Consent-Ledger
  bleibt (er ist der Nachweis, dass eine Einwilligung bestand und endete).
- Der Handler öffnet **mitglieds-gescopt** (`user_id=member_id`) — mit falschem Scope sähe er
  null Zeilen und täte still nichts, die schlimmere Variante.

## Web (9-S8)
- Die Sektion sitzt auf **`/profile`** (mitglieds-privat), nicht auf einer Haushalts-Seite — und
  ist zugleich das Ziel des Callback-Redirects.
- **Nie einen Messwert rendern.** Die UI sagt *ob* verbunden und *welche* Typen zugestimmt sind,
  nie *was* gemessen wurde. Ein Test hält das fest.
- Consent-PATCH schickt die **vollständige neue Menge**, nie ein Delta.
- Verbinden ist eine **volle Navigation**, kein Popup (der Callback ist ein server-seitiger
  Redirect).

## No-Gos
- **Nie** einen Read ohne `member_id`-Scope — und **nie** die RLS-Policy auf `household_id`
  zurückbauen.
- **Nie** Wearable-Daten an andere Mitglieder ausgeben, auch nicht aggregiert, auch nicht an
  Admins, auch nicht an die Betreiber-Konsole.
- **Nie** Token/Refresh-Token/`code`/`state` in Response, Log oder Event-Payload.
- **Nie** Klartext-Tokens persistieren; **nie** außerhalb des Service ver-/entschlüsseln.
- **Nie** ein haushaltsweites Domain-Event für Wearable-Vorgänge.
- **Nie** einen Soft-Delete einführen (Art. 9); **nie** den Consent-Ledger löschen.
- **Nie** Wearables für Kinder-Accounts — und der Cron muss eine nachträgliche Herabstufung
  aufräumen, nicht nur ignorieren.
- **Nie** unter `custode_maint` in die Wearable-Tabellen schreiben (die Policy verbietet es;
  einzige Ausnahme ist der DELETE des Retention-Jobs auf `wearable_daily`).
- **Nie** einen abgelehnten Refresh stillschweigend jede Nacht wiederholen — `needs_reauth`.
