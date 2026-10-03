# Fehler-Referenzkatalog (RFC 9457)

> Jede API-Fehlerantwort ist `application/problem+json` mit einem **stabilen
> `type`** (Clients verzweigen darauf, nie auf Message-Strings) und einem
> **`reference`** (Kurzcode aus `request_id`, beim Nutzer kopierbar → Trace/Logs/
> Sentry, ARCHITECTURE §12). Konvention: `type = https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#<slug>`.

Antwort-Form (Beispiel):

```json
{
  "type": "https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#validation",
  "title": "Eingabe ungültig",
  "status": 422,
  "detail": "Validierung fehlgeschlagen.",
  "reference": "CUS-7Q2F-9K",
  "errors": [{ "type": "missing", "loc": ["body", "email"], "msg": "Field required" }]
}
```

`errors` ist Pydantics Rohformat — nicht `{field, code}`, wie dieses Beispiel bis 11-A2
behauptete. Zusatzfelder werden **flach** in den Body gemergt, nicht verschachtelt; heute gibt es
drei: `households` (bei `last_admin`), `category` (bei `caldav_write_failed`) und `field` (bei
`external_field_readonly`).

## Die Regel und das Gate

Neue Codes werden hier ergänzt, **bevor** sie im Code verwendet werden — und seit 11-A2 hängt das
nicht mehr an Disziplin: `backend/tests/test_error_catalogue.py` hält Katalog und Code in **beide**
Richtungen gegeneinander. Ein Slug im Code ohne Eintrag macht CI rot; ein Eintrag ohne Erzeuger
ebenso. Die zweite Richtung ist die unauffälligere — ein dokumentierter Fehler, den es nicht gibt,
sieht aus wie Abdeckung. Genau so standen `ssrf_blocked`, `payload_too_large` und
`idempotency_replay` hier, während der Code `import_url_blocked`, `file_too_large` und gar nichts
warf.

Ein `slug=`, das kein Literal ist, entzieht sich dem Gate und muss dort ausdrücklich quittiert
werden (`_DYNAMIC_SLUGS`). Heute gibt es genau einen Fall: `only_children`.

---

## Querschnitt (`kernel`) — jede Route kann diese liefern

| slug | HTTP | Bedeutung |
|---|---|---|
| `validation` | 422 | Pydantic-/Schema-Validierung fehlgeschlagen; `errors` trägt die Rohdetails |
| `unauthorized` | 401 | nicht authentifiziert (Access-Cookie fehlt, abgelaufen oder unbekannt) |
| `forbidden` | 403 | authentifiziert, aber Rolle/Recht fehlt (AuthZ-Matrix) — auch ohne aktiven Haushalt |
| `not_found` | 404 | Ressource existiert nicht — oder gehört einem fremden Haushalt (RLS antwortet wie „nicht da") |
| `bad_request` | 400 | Starlette-eigene 400 (fehlerhafte Anfrage vor der Fachschicht) |
| `conflict` | 409 | Starlette-eigene 409 ohne Fach-Slug |
| `conflict_version` | 412 | Starlette-eigene 412. **Der Fach-Pfad heißt `precondition_failed`** |
| `rate_limited` | 429 | Starlette-eigene 429. **Der gebaute Fall heißt `too_many_attempts`** |
| `error` | — | Rückfall für eine `HTTPException` ohne bekannten Status |
| `internal` | 500 | unerwarteter Fehler. Seit 11-A2 gebaut: `problem+json` **mit** `reference`, ohne Ausnahmetyp und ohne Meldung — die Einzelheiten stehen im Log, nicht in der Antwort |

### Bedingte Anfragen (ETag/If-Match, ADR-0034)

| slug | HTTP | Bedeutung |
|---|---|---|
| `precondition_required` | 428 | `If-Match` fehlt bei einem Schreibvorgang, der es verlangt |
| `precondition_failed` | 412 | `If-Match` passt nicht zur aktuellen `version` — verlorener Update verhindert |

### Sync-Batch (ARCHITECTURE §10)

| slug | HTTP | Bedeutung |
|---|---|---|
| `sync_unknown_entity` | 422 | Der Batch nennt einen Entitätstyp, den die Modul-Spec nicht kennt |
| `sync_unknown_field` | 422 | Feld außerhalb der `fields` der Entität — der Client schreibt etwas, das er nicht schreiben darf |
| `sync_invalid_field` | 422 | Feldwert hat den falschen Typ/das falsche Format |
| `sync_missing_fields` | 422 | Ein `create` ohne die in `required_on_create` genannten Felder |
| `resync_required` | 410 | Der Pull-Cursor ist zu alt; der Client muss von vorn laden |

### Dateien und Bilder

| slug | HTTP | Bedeutung |
|---|---|---|
| `file_too_large` | 413 | Upload über dem Limit (Rezeptfoto, Anleitungs-Anhang) |
| `invalid_image` | 422 | Kein dekodierbares Bild bzw. ein Format, das wir nicht re-encodieren |
| `storage_unavailable` | 503 | Kein Blob-Speicher konfiguriert (Null-Adapter) — Uploads sind aus, Lesen bleibt |
| `export_too_large` | 413 | Der Datenexport überschreitet die Zeilengrenze; die Absage kommt beim **Sammeln**, nicht am fertigen Archiv (ADR-0083) |

### Ausgehende Abrufe (Rezept-Import, `kernel/fetch`)

| slug | HTTP | Bedeutung |
|---|---|---|
| `import_url_blocked` | 400 | Ziel ist privat/nicht erlaubt, falsches Schema, oder ein Redirect verließe die Origin. **Ein** undurchsichtiger Slug für jede SSRF-Ablehnung — welche Regel griff, verrät die Antwort bewusst nicht |
| `import_fetch_failed` | 400 | Die Quelle antwortete nicht oder mit einem Fehler |
| `import_too_large` | 400 | Antwort über der Größengrenze |
| `import_too_many_redirects` | 400 | Redirect-Kette zu lang |

### Serverseitige Verschlüsselung (ADR-0077)

| slug | HTTP | Bedeutung |
|---|---|---|
| `crypto_unconfigured` | 503 | `CUSTODE_CRYPTO_KEY` fehlt — Funktionen mit fremden Zugangsdaten (CalDAV, Wearables) antworten 503 statt still zu scheitern |

---

## `accounts` / Auth (Phase 1)

| slug | HTTP | Bedeutung |
|---|---|---|
| `invalid_credentials` | 401 | E-Mail/Passwort falsch — **oder** das Konto ist zur Löschung vorgemerkt. Bewusst dieselbe Antwort: ein eigener Slug verriete, dass es das Konto gab. Konstant-zeitig, keine Enumeration |
| `invalid_token` | 401 | Refresh-Token unbekannt oder Refresh-Cookie fehlt |
| `expired_token` | 401 | Refresh-Token abgelaufen |
| `token_reuse` | 401 | Ein bereits verbrauchtes Refresh-Token wurde erneut vorgelegt → Diebstahl-Signal, die **ganze** Familie wird widerrufen |
| `csrf_failed` | 403 | Double-Submit-Token fehlt oder passt nicht |
| `weak_password` | 422 | Passwort erfüllt die Policy nicht |
| `pwned_password` | 422 | Passwort steht in einer bekannten Leak-Liste (HIBP k-anonymity) |
| `email_taken` | 409 | E-Mail bereits registriert |
| `username_taken` | 409 | Benutzername im Haushalt vergeben (Kinder-Konto) |
| `weak_pin` | 422 | Kinder-PIN zu einfach |
| `invalid_pin` | 401 | Kinder-PIN falsch |
| `too_many_attempts` | 429 | Zu viele fehlgeschlagene PIN-Versuche — der real gebaute 429 |
| `reset_invalid` | 400 | Passwort-Reset-Token unbekannt, verbraucht oder abgelaufen |
| `verify_invalid` | 400 | E-Mail-Bestätigungstoken unbekannt, verbraucht oder abgelaufen |
| `invite_expired` | 410 | Einladungscode abgelaufen |
| `invite_exhausted` | 409 | Einladungscode ist aufgebraucht (`max_uses`) |
| `already_member` | 409 | Bereits Mitglied dieses Haushalts |
| `totp_required` | 401 | Login braucht einen TOTP- oder Recovery-Code (das Passwort war richtig) |
| `totp_invalid` | 422 | TOTP-/Recovery-Code falsch |
| `totp_already_enabled` | 409 | 2FA ist bereits aktiv |
| `totp_not_set_up` | 409 | Aktivieren ohne vorheriges `setup` |
| `totp_not_enabled` | 409 | Deaktivieren/Recovery-Codes ohne aktive 2FA |
| `passkey_challenge_expired` | 400 | Die WebAuthn-Challenge ist abgelaufen (Redis-TTL) — Zeremonie neu starten |
| `passkey_invalid` | 400/401 | Attestation/Assertion ungültig |
| `passkey_exists` | 409 | Dieser Authenticator ist bereits registriert |

### Austritt, Kontolöschung, Haushalts-Auflösung (Phase 11)

Vier Abweisungen, die einander ähnlich sehen und **verschiedene Dinge bedeuten**. Der Unterschied
entscheidet, was die Person als Nächstes tun kann — sie zu einem „das geht nicht" zusammenzufassen
hieße, jemandem zu sagen, er solle eine Rolle an eine Person übergeben, die es nicht gibt.

| slug | HTTP | Bedeutung | Ausweg |
|---|---|---|---|
| `last_admin` | 409 | Letzte Verwaltung eines Haushalts, in dem noch **Erwachsene** sind. `extra.households` nennt die betroffenen Haushalte | **Behebbar:** Rolle unter `/account` übergeben |
| `only_children` | 409 | Außer der Person leben dort nur Kinder oder Gäste — niemand *kann* übernehmen. Wird per `slug=reason` erzeugt (`exit_blocker_reason`), nicht als Literal | **Haushalt auflösen** (`POST /v1/household/dissolve`) |
| `sole_member` | 409 | Allein im Haushalt: man tritt nicht aus, man löst auf. Gibt es **nur** beim Austritt — die Kontolöschung lässt den Fall bewusst zu, weil Art. 17 ein Recht ist und es dort kein „stattdessen" gibt | **Haushalt auflösen** |
| `child_cannot_leave` | 409 | Ein Kinder-Konto kann nicht selbst austreten: es hat weder E-Mail noch Passwort und käme nie zurück | Die Verwaltung entfernt das Mitglied |
| `already_dissolved` | 409 | Der Haushalt ist bereits aufgelöst | — |
| `name_mismatch` | 422 | Der abgetippte Haushaltsname stimmt nicht — die Bestätigung der Auflösung | Namen genau abtippen |
| `household_dissolved` | 410 | Der Haushalt wurde aufgelöst; der Zugang ist beendet | Neuen Haushalt anlegen oder beitreten |

---

## `backoffice` / Betreiber-Konsole (`/ops`, Phase 8)

Eigener Auth-Stack: opaker **Bearer**-Token (kein Cookie/CSRF). Fehler sind fail-closed — jeder
Auth-Fehlschlag ist 401, ohne Operator-Enumeration.

| slug | HTTP | Bedeutung |
|---|---|---|
| `invalid_credentials` | 401 | Operator-Login falsch (Passwort **oder** TOTP; konstant-zeitig) |
| `unauthorized` | 401 | Bearer-Token fehlt, abgelaufen, unbekannt — oder der Operator ist inaktiv |
| `invalid_flag` | 422 | Unbekannter Flag-Schlüssel |
| `cannot_deactivate_self` | 409 | Ein Operator kann sich nicht selbst deaktivieren |
| `cannot_deactivate_last` | 409 | Der letzte aktive Operator bleibt — sonst gäbe es keinen Weg zurück in die Konsole |
| `not_found` | 404 | Unbekanntes Banner bzw. unbekannter Haushalt |

KPIs, Support-Suche und Feedback-Inbox lesen nur Aggregat-Views und haben über die Auth hinaus
keine eigenen Fehler.

---

## `tasks` (Phase 4)

| slug | HTTP | Bedeutung |
|---|---|---|
| `title_required` | 422 | Ad-hoc-Instanz ohne Titel (aus einem Template kommt er aus dem Snapshot) |
| `invalid_state` | 409 | Zustandsmaschine: erledigen/zuweisen setzt `open` voraus |

---

## `economy` (Phase 4)

| slug | HTTP | Bedeutung |
|---|---|---|
| `insufficient_funds` | 422 | Deckungsprüfung des Ledgers — der Saldo trägt die Buchung nicht. Die Invariante „keine negativen Salden" (KONZEPT §5.9) ist hier durchgesetzt, nicht nur behauptet |
| `invalid_amount` | 422 | Betrag ≤ 0 |
| `invalid_transfer` | 422 | Quelle == Ziel, oder eine Buchung, die es nicht geben darf |
| `reward_inactive` | 409 | Belohnung ist abgeschaltet |
| `out_of_stock` | 409 | Belohnung ist aufgebraucht (`stock`) |
| `cooldown_active` | 409 | Belohnung hat eine Sperrfrist, die noch läuft |
| `thanks_cap_reached` | 422 | Das Tageslimit für Danke-Punkte ist erreicht |
| `invalid_state` | 409 | Die Einlösung ist nicht im erwarteten Zustand |

---

## `marketplace` (Phase 4)

| slug | HTTP | Bedeutung |
|---|---|---|
| `not_your_task` | 403 | Nur die zugewiesene Person kann ihre Aufgabe anbieten |
| `already_listed` | 409 | Für diese Instanz gibt es bereits ein offenes Angebot |
| `not_seller` | 403 | Zurückziehen darf nur der Verkäufer |
| `invalid_state` | 409 | Das Angebot ist nicht im erwarteten Zustand (offen/angenommen) |
| `invalid_transfer` | 422 | Das eigene Angebot annehmen |
| `task_not_done` | 409 | Abrechnen setzt eine erledigte Aufgabe voraus |
| `task_already_done` | 409 | Rückabwicklung einer **erfüllten** Aufgabe. Ein erledigter Handel wird abgerechnet, nicht rückabgewickelt — der Verkäufer bekäme sonst die Arbeit **und** seine Punkte zurück (11-B1). Heute erreicht kein Endpunkt diesen Weg; der Wächter steht für den Escrow-Verfall-Cron |

---

## `calendar` (Phase 5 + 9)

| slug | HTTP | Bedeutung |
|---|---|---|
| `not_owner` | 403 | Persönliche Termine ändert nur ihr Eigentümer |
| `invalid_rrule` | 422 | Wiederholungsregel nicht interpretierbar |
| `invalid_tzid` | 422 | Unbekannte Zeitzone |
| `invalid_range` | 422 | Ende vor Anfang, oder ein Zeitfenster außerhalb der erlaubten Spanne |
| `not_a_series` | 422 | Serien-Operation auf einem Einzeltermin |
| `not_an_occurrence` | 422 | Der genannte Zeitpunkt ist kein Termin der Serie |
| `occurrence_cancelled` | 422 | Der Einzeltermin ist abgesagt |
| `subscription_exists` | 409 | Diese CalDAV-URL ist im Haushalt bereits abonniert |
| `external_event_read_only` | 409 | Gespiegelte Fremdtermine werden nicht lokal geändert |
| `external_field_readonly` | 422 | Dieses Feld trägt der Write-back nicht zurück; `extra.field` nennt es |
| `external_not_synced` | 409 | Der Termin ist (noch) nicht mit dem Fremdserver abgeglichen |
| `external_conflict` | 409 | Der Fremdserver hat den Termin inzwischen geändert (ETag-Konflikt) |
| `external_kind_unsupported` | 422 | Der Fremdserver liefert einen Objekttyp, den wir nicht spiegeln |
| `external_tzid_unsupported` | 422 | Zeitzone des Fremdtermins nicht auflösbar |
| `caldav_disabled` | 503 | Kill-Switch aus — kein ausgehender Sync |
| `caldav_write_failed` | 502 | Der Fremdserver hat den Write-back abgelehnt; `extra.category` nennt die Klasse |

---

## `scheduling` (Phase 5)

| slug | HTTP | Bedeutung |
|---|---|---|
| `invalid_hours` | 422 | Arbeits-/Sperrzeiten nicht interpretierbar |
| `invalid_range` | 422 | Zeitfenster ungültig |

---

## `mealplanner` (Phase 6)

| slug | HTTP | Bedeutung |
|---|---|---|
| `no_candidate` | 404/422 | Die Automatik findet unter den Vorgaben kein Gericht |
| `no_recipe` | 422 | Der Slot trägt kein Rezept |
| `no_dish` | 422 | Kein Gericht zum Kochen vorgemerkt |
| `no_prep` | 422 | Keine Vorbereitungs-Aufgabe zu erzeugen |

---

## `recipes` (Phase 2)

| slug | HTTP | Bedeutung |
|---|---|---|
| `import_no_recipe` | 422 | Unter der URL war kein erkennbares Rezept |

Die übrigen Import-Fehler (`import_url_blocked`, `import_fetch_failed`, `import_too_large`,
`import_too_many_redirects`) kommen aus `kernel/fetch` und stehen im Querschnitt.

---

## `capture` — Zuruf (Phase 4/7)

| slug | HTTP | Bedeutung |
|---|---|---|
| `invalid_state` | 409 | Der Eintrag ist bereits bestätigt oder verworfen |
| `no_target` | 409 | Der Vorschlag nennt kein Ziel, das sich anlegen ließe |

---

## `links` (Phase 7)

| slug | HTTP | Bedeutung |
|---|---|---|
| `invalid` | 422 | Verknüpfung auf sich selbst oder ein unbekannter Objekttyp |

---

## `vault` (Phase 7)

| slug | HTTP | Bedeutung | Was die Person tun kann |
|---|---|---|---|
| `vault_already_set_up` | 409 | Der Haushalt hat bereits einen Recovery-Umschlag; `PUT /v1/vault/keys` mit `kind=recovery` ersetzt ihn nie. Der Server kann nicht prüfen, ob ein zweiter Umschlag denselben Haushaltsschlüssel trägt (opak) — ein Ersetzen würde den Schlüssel unter allen anderen Mitgliedern austauschen | Dem bestehenden Tresor **beitreten**: Wiederherstellungs-Code des Haushalts eingeben, eigene Passphrase festlegen |

---

## `wearables` (Phase 9)

| slug | HTTP | Bedeutung |
|---|---|---|
| `feature_disabled` | 403 | Haushalts-Flag `wearables` aus (Default), nur beim Verbinden. **Lesen und Löschen bleiben offen** — ein abgeschaltetes Flag darf niemanden von seinen eigenen Daten aussperren |
| `connection_exists` | 409 | Für dieses Mitglied besteht bereits eine Verbindung |
| `crypto_unconfigured` | 503 | Ohne Server-Schlüssel werden keine fremden Tokens gespeichert. Bewusst **vor** dem Redirect zum Provider |
| `wearables_disabled` | 503 | Kill-Switch aus oder Betreiber-Zugangsdaten fehlen → Null-Adapter |
| `not_found` | 404 | Fremde/unbekannte Verbindung — **auch für Admins** (N-2: die Antwort bestätigt nicht einmal die Existenz) |

### Callback-Codes (kein `problem+json`)

`GET /v1/wearables/oura/callback` antwortet einem Browser mit **302**, nie mit problem+json — eine
Top-Level-Navigation kann keinen Fehler-Body zeigen. Dieselben Ursachen reisen als `?error=`-Query
nach `<public_base_url>/profile`. Das sind **keine** Slugs im obigen Sinne und stehen deshalb nicht
unter dem Gate:

`denied` (Nutzer hat beim Provider abgelehnt) · `state_invalid` (unbekannt, abgelaufen, erneut
verwendet, oder das Cookie gehört einem anderen Browser) · `exchange_failed` · `forbidden` (die
Rolle wechselte im Callback-Fenster auf `child`) · `crypto_unconfigured`.
Weder Token noch `code` noch `state` erscheinen im Redirect-Ziel.

---

## Phase-8-Endpunkte (App-Seite)

`/v1/feedback`, `/v1/banners`, `/v1/household/digest`, `/v1/notes/trash` + `/v1/notes/{id}/untrash`
nutzen ausschließlich Querschnitts-Slugs: `validation` (z. B. unbekannte Feedback-Kategorie),
`forbidden` (kein Admin bzw. kein aktiver Haushalt beim Digest-Toggle), `not_found` (z. B.
`untrash` einer Notiz, die nicht im Papierkorb liegt).

---

## `feature_disabled` als Querschnitt

Wird heute nur von `wearables` erzeugt. Mit der Flag-Durchsetzung (Roadmap Phase 11) wird er der
Slug **jedes** abgeschalteten Moduls — dann gehört er in den Querschnitt, nicht hierher.

---

## Regeln

- Nie Stacktraces nach außen; nie Inhalte/PII in `detail`.
- **Jeder 5xx trägt einen `reference`-Code** — seit 11-A2 auch der unerwartete.
- Clients verzweigen auf `type`, nie auf `title`/`detail`. Beide sind Anzeigetexte und dürfen sich
  ändern, ohne dass ein Client bricht.
