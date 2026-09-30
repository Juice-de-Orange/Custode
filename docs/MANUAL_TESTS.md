# Manuelle Tests

Was die automatisierten Gates **strukturell nicht abdecken können** — echte Browser, echte Geräte,
echte Fremdserver, echter Zeitablauf, zweite Accounts, der Compose-/Deploy-Pfad. Alles andere
gehört in einen Test, nicht hierher.

> **Hier stehen Protokolle, keine Verpflichtungen.** Was der Betreiber *schuldet* — Zugangsdaten
> erzeugen, fremde Konten registrieren, Rollen anlegen, Entscheidungen treffen — führt er in einer
> eigenen Betreiber-Checkliste (nicht im Repo). Diese Datei sagt, **wie** ein Durchgang aussieht.
> Ein Punkt gehört in genau eine der beiden — zwei Listen, die dasselbe behaupten, sind die
> Fehlerklasse aus BUGLOG 2026-07-31.

**Wie das benutzt wird:** Abschnitt A einmalig, sobald der Export das erste Mal auf Prod läuft.
Abschnitt B einmalig, sobald ein echter CalDAV-Server bereitsteht. Abschnitt C+D vor jedem Release
bzw. bevor neue F&F-Haushalte dazukommen. Abschnitt E einmalig nach der Oura-Registrierung.

Kopiere den betreffenden Abschnitt in ein Issue/eine Notiz und hake dort ab — diese Datei ist die
**Vorlage**, sie wird nicht mit Häkchen committet.

> Jede Zeile nennt die **Erwartung**. Steht keine da, ist die Zeile unbrauchbar und gehört
> korrigiert. Ein „sieht gut aus" ist kein Testergebnis.

---

## Vorbedingungen — zuerst prüfen, sonst sind halbe Ergebnisse falsch

Diese vier Punkte erklären die meisten „warum passiert nichts"-Momente:

- [ ] **Der Worker-Prozess läuft.** Nicht nur die Cron-Jobs — der Outbox-Dispatcher ist ein
      In-Process-Loop (~1 s Poll, `backend/app/worker.py`). **Ohne ihn** funktionieren SSE-Live-
      Aktualisierung, Zuruf-Aktionsketten, der Kommentar-/Verknüpfungs-Reaper und die
      Feedback→GitHub-Weiterleitung nicht — ohne jede Fehlermeldung.
      *Erwartung:* `docker compose … ps worker` → `running (healthy)`.
- [ ] **Der Testhaushalt hat Daten.** Ein leerer Haushalt bestätigt nur Empty-States — genau so
      blieb der Dexie-Bug ein halbes Jahr unentdeckt (BUGLOG 2026-07-19).
      *Erwartung:* mindestens Rezepte, Aufgaben, Einkaufsposten und Termine vorhanden.
- [ ] **Mindestens ein Durchgang mit FRISCHEM Login** (neues Browser-Profil, nicht die Session,
      die die Daten angelegt hat) — BUGLOG 2026-07-08 (#132).
- [ ] **Zweiter Account im selben Haushalt** — sieben Punkte sind ohne ihn nicht durchführbar
      (Marke **[2×]**, s. Legende in Abschnitt C).

### Cron-Jobs von Hand antriggern

Nicht auf Montag 07:00 warten. Im laufenden Worker-Container:

```bash
docker compose -f docker-compose.dev.yml exec worker python -c \
  "import asyncio; from app.worker import sync_external_calendars_job as j; asyncio.run(j.original_func())"
```

`original_func` umgeht den taskiq-Wrapper und ruft die Funktion direkt in-process auf. Ersetzbar
durch `send_weekly_digest_job` (Digest), `reap_deleted_job` (30-Tage-Purge), `reap_outbox`,
`reap_sync_ops_job`, `ingest_wearables_job` (Oura-Ingest), `reap_wearable_daily_job`
(90-Tage-Retention) und **`purge_due_accounts_job`** (Konto-Purge nach der Karenz, 11-S1d).
Auf Prod dieselbe Zeile mit `-f docker-compose.prod.yml`.

---

## A — Datenexport (Art. 15/20, ADR-0083): der erste echte Durchgang

Neu und noch nie außerhalb der Testsuite gelaufen. Die Gates prüfen den Export gegen eine
Testcontainer-DB, mit einem gesetzten Principal und gegen ein jsdom — **nicht** gegen echte
Cookies, echte DB-Rollen, echte Blobs, einen echten Proxy, eine echte Download-Leiste und ein
echtes Entpackprogramm. Genau das steht hier. Bedienstelle ist die Sektion „Datenexport" auf
`/profile`.

- [ ] **Echter Download im Browser.** `/profile` → „Meine Daten exportieren".
      *Erwartung:* während des Laufs erscheint der Hinweis „Das Archiv wird zusammengestellt", der
      Knopf ist gesperrt; danach liegt `custode-export-personal-<JJJJ-MM-TT>.zip` in den Downloads
      und die Sektion **nennt den Dateinamen**. Kein 401, kein Login-Redirect, kein leerer
      Download namens `download`.
- [ ] **[Gerät]** **Derselbe Knopf auf dem Telefon** (iOS Safari **und** Android Chrome).
      Blob-Downloads sind genau dort das klassische Bruchstück, und kein jsdom-Test sieht das.
      *Erwartung:* die Datei landet in „Dateien"/„Downloads" und lässt sich dort öffnen. Klemmt
      es, ist der Umweg `https://<domain>/v1/me/export` in der Adresszeile (Top-Level-GET, das
      Access-Cookie ist `SameSite=Lax` mit `path=/` und kommt mit, ADR-0021) — dass der Umweg
      geht, ist zugleich der Beleg, dass das Problem im Browser liegt und nicht am Server.
- [ ] **ZIP mit dem Bordmittel öffnen** (Doppelklick / `unzip`, nicht mit Python).
      *Erwartung:* `manifest.json`, `LIESMICH.txt` und mehrere `data/<tabelle>.json`;
      LIESMICH.txt zeigt **Umlaute korrekt** (UTF-8, kein `Anhänge`).
- [ ] **Inhalt plausibel.** Eine Notiz und ein Termin, die man selbst angelegt hat, in
      `data/notes.json` bzw. `data/calendar_events.json` wiederfinden. Setzt die Vorbedingung
      „Testhaushalt hat Daten" voraus — ein leerer Haushalt bestätigt nur, dass die Datei existiert.
      *Erwartung:* Titel und Zeitstempel stimmen mit dem überein, was die App zeigt.
- [ ] **Manifest gegenlesen.** `manifest.json` öffnen.
      *Erwartung:* `scope` stimmt; `withheld_columns` nennt u. a. `users.password_hash`;
      `excluded_tables` nennt jede ausgeschlossene Tabelle **mit Begründung**; `skipped_tables`
      erklärt beim persönlichen Export, warum z. B. `recipes` fehlt. Ein Manifest mit leeren Listen
      wäre der Befund.
- [ ] **Redaktion mit eigenen Augen.** `data/users.json` öffnen.
      *Erwartung:* `password_hash` und `totp_secret` stehen da — mit dem Wert `"<redaktiert>"`, der
      Schlüssel fehlt **nicht**. Danach im entpackten Ordner nach dem eigenen CalDAV-App-Passwort
      und dem Vault-Passwort suchen (`grep -ri`). *Erwartung:* null Treffer.
- [ ] **Anhänge — nur der Haushalts-Export hat welche.** Als Admin auf `/profile` den zweiten
      Knopf („Haushaltsdaten exportieren"). Rezeptfotos und Anleitungs-Anhänge hängen an
      haushaltsgeteilten Tabellen, im persönlichen Export sind sie deshalb **nie** enthalten.
      *Erwartung:* `attachments/` enthält so viele Dateien, wie der Haushalt Rezeptfotos +
      Anleitungs-Anhänge hat; ein Bild per Doppelklick geöffnet zeigt **das erwartete Foto** und
      hat nicht 0 Bytes. Steht im Manifest `attachments.storage_available: false`, ist auf diesem
      Deployment kein Blob-Speicher konfiguriert — dann ist **das** der Befund, nicht der Export.
- [ ] **Rollen live.** Mit einem `member`-Konto auf `/profile`.
      *Erwartung:* nur **ein** Knopf; der Haushalts-Export wird gar nicht angeboten. Direkt
      `https://<domain>/v1/household/export` aufrufen — *Erwartung:* 403, das Angebot war also
      nicht die Absicherung. Mit einem **Kind-Konto** auf `/profile`: *Erwartung:* der eigene
      Export ist da und liefert eine echte ZIP — das Betroffenenrecht gehört der Person.
- [ ] **[2×] Art. 9 auf der echten Datenbank.** Zweites Mitglied verbindet ein Wearable (oder eine
      `wearable_daily`-Zeile von Hand setzen), dann als **Admin** den Haushalts-Export ziehen und
      `data/wearable_daily.json` + `data/wearable_connections.json` öffnen.
      *Erwartung:* **keine** fremde `member_id`. Warum das trotz grüner Tests hierher gehört: die
      Suite legt ihre Rollen selbst als `NOSUPERUSER NOBYPASSRLS` an — hätte die App-Rolle auf
      dem Produktivsystem Ownership oder `BYPASSRLS`, wäre die einzige Mandantengrenze dieses Exports still
      wirkungslos, und kein Gate könnte das sehen.
- [ ] **Größe und Dauer eines echten Haushalts notieren.** Wie groß ist die Datei, wie lange
      dauert der Aufruf?
      *Erwartung:* deutlich unter der 64-MiB-Grenze und ohne Proxy-Timeout (der Export läuft
      **synchron** im Request; Caddy und uvicorn müssen die Antwort in einem Stück durchreichen).
      Notieren, nicht nur abhaken — die Zahl entscheidet, wann die Job-Variante nötig wird.

---

## B — CalDAV gegen einen echten Server

**Bisher lief nichts davon.** Der gesamte Stack (#143/#145/#146/#147/#148) ist ausschließlich gegen
einen Radicale-Testcontainer getestet; gegen Nextcloud/iCloud/Google wurde nie etwas ausgeführt.
Google braucht ohnehin den OAuth-Folge-Slice, iCloud ist derzeit nicht nutzbar.

**Vorher bewusst machen:** Der Reaper purgt seit #145 auch `calendar_events` und
`external_calendar_subscriptions` — lokal gelöschte Termine sind nach 30 Tagen endgültig weg.
Nicht mit einem Kalender testen, an dem etwas hängt.

- [ ] **Abo anlegen.** `/calendar` → „Externe Kalender (CalDAV)" → „Abo hinzufügen" → Bezeichnung,
      CalDAV-URL, Benutzername/Passwort → „Abonnieren".
      *Erwartung:* Abo erscheint, **kein** `503 crypto_unconfigured` (sonst → Abschnitt A).
- [ ] **Verbindung prüfen** (der schnelle Weg): am Abo „Verbindung prüfen" klicken.
      *Erwartung:* sofort „Erreichbar — N Einträge gefunden." Das ersetzt das Warten auf den
      15-Minuten-Cron beim Einrichten; bei Tippfehlern kommt direkt die Kategorie (`auth_failed`,
      `unreachable`, …) statt einer Viertelstunde Rätselraten.
- [ ] **Pull-Sync.** Sync antriggern (s. o.) statt zu warten.
      *Erwartung:* externe Termine erscheinen in der Agenda mit Badge „**Extern**"; Statuszeile
      „Zuletzt synchronisiert: …" mit aktueller Zeit, kein Fehlertext.
- [ ] **Write-back.** Termin anlegen mit „Ziel-Kalender" = das Abo.
      *Erwartung:* Der Termin taucht **im externen Kalender** auf (dort nachsehen, nicht nur in
      Custode).
- [ ] **Property-Erhalt — der Kern von ADR-0080.** Den Termin im externen Client um eine
      **Erinnerung (VALARM)** und einen **Teilnehmer** anreichern, dann in Custode Titel/Zeit ändern.
      *Erwartung:* Erinnerung und Teilnehmer überleben die Custode-Änderung (GET-modify-PUT).
      Das ist der wertvollste Einzeltest in diesem Abschnitt.
- [ ] **Konflikt.** Denselben Termin quasi-gleichzeitig in beiden Systemen ändern, dann in Custode
      speichern.
      *Erwartung:* `409 external_conflict` mit verständlicher Meldung — **kein** stiller
      Datenverlust. Danach Sync antriggern → *Erwartung:* der Zustand heilt sich (Remote gewinnt).
- [ ] **Falsche Zugangsdaten.** Passwort im Abo absichtlich verfälschen, „Verbindung prüfen".
      *Erwartung:* sofort `auth_failed` im Klartext. Danach Sync antriggern.
      *Erwartung:* deutsche Status-Zeile für die Kategorie `auth_failed` — nicht „unbekannter
      Fehler", nicht die URL im Klartext.
- [ ] **Unerreichbarer Server.** URL auf einen toten Host zeigen lassen.
      *Erwartung:* Kategorie `unreachable`, das Abo bleibt bestehen, andere Abos syncen weiter
      (Failure-Isolation).
- [ ] **Serie mit Ausnahme.** Im externen Client eine wöchentliche Serie anlegen und **einen**
      Termin abweichend verschieben (`RECURRENCE-ID`), dann spiegeln.
      *Erwartung:* Die Ausnahme wird **ignoriert**, der Master gewinnt — dokumentierte Lücke
      (`docs/MODULES/calendar.md`). Hier bewerten, ob das im Alltag tragbar ist oder ein Slice wird.
- [ ] **Externe Termine sind schreibgeschützt.** An einem gespiegelten Termin nach
      „Verschieben"/„Absagen" suchen.
      *Erwartung:* Aktionen sind ausgeblendet (das Backend würde 409 antworten).
- [ ] **Löschen mit Kaskade.** Externen Termin in Custode löschen.
      *Erwartung:* Confirm nennt ausdrücklich die Remote-Löschung; danach ist er auch im externen
      Kalender weg. Abo löschen → Confirm nennt die Spiegel-Kaskade.
- [ ] **Pausieren.** „Pausieren" am Abo.
      *Erwartung:* Pull stoppt (Statuszeile sagt es), Write-through läuft weiter.
- [ ] **Self-Hosted im LAN** (falls zutreffend, z. B. NAS-Nextcloud): Ohne
      `CUSTODE_CALDAV_ALLOW_PRIVATE_URLS=true` blockt der SSRF-Guard private Adressen.
      *Erwartung:* geblockt mit klarer Meldung; mit gesetztem Flag funktioniert es.

---

## C — Release-Regression über die Module

Je Modul der Happy-Path plus der eine Pfad, den Tests strukturell nicht treffen. Kürzel:
**[2×]** braucht zwei Accounts/Geräte · **[Gerät]** braucht echtes Telefon/echten Browser ·
**[Zeit]** braucht Zeitablauf oder Cron-Trigger · **[Extern]** braucht einen Fremddienst.

### Konten, Haushalt, Sicherheit — `/`, `/login`, `/register`, `/profile`, `/security`
- [ ] Registrieren → Auto-Login landet auf `/`. Haushalt anlegen. Einladung erstellen —
      *Erwartung:* Code wird **genau einmal** angezeigt.
- [ ] Zweiter Account tritt per Code bei; „Wechseln" zwischen Haushalten funktioniert.
- [ ] 2FA einrichten (QR → Code → „Aktivieren") — *Erwartung:* Recovery-Codes erscheinen einmalig.
      Danach ausloggen, mit 2FA einloggen.
- [ ] Flag `wearables` an → `/profile` zeigt die Wearable-Sektion.
      **[2×]** *Erwartung:* ein zweites Mitglied (auch ein Admin) sieht dort **nie** die fremde
      Verbindung — das ist N-2 im Alltag.
- [ ] **[Gerät]** Passkey hinzufügen (`/security`) und damit einloggen (`/login` → „Mit Passkey
      anmelden"). *Erwartung:* Touch ID/Windows Hello greift; CI testet nur mit Software-Authenticator.
- [ ] **[2×]** `/security` → „Aktive Sitzungen" → fremde Sitzung abmelden.
      *Erwartung:* Die Liste unterscheidet „dieses Gerät" von anderen; das andere Gerät ist
      danach ausgeloggt.
- [ ] **[Extern]** Passwort vergessen → Mail kommt an → Link setzt neues Passwort.
      E-Mail-Verifikation ebenso. *Erwartung:* echte Mailbox, nicht der Null-Adapter.
- [ ] Kinder-Konto anlegen (Name/Benutzername/PIN). Login **nur** über
      `/child-login?household=<uuid>` — *Erwartung:* ohne den Parameter nur „Kein Haushalt
      angegeben"; nach 5 Fehlversuchen „Zu viele Versuche".
- [ ] **Eingeloggt ohne aktiven Haushalt:** Auf einer beliebigen Modulroute
      *Erwartung:* freundlicher `NoHouseholdState`, **keine** 403-Wand (#132).

### Aufgaben & Räume — `/tasks`, `/rooms`
- [ ] Vorlage anlegen (Admin) → Aufgabe daraus anlegen → „Erledigt".
      *Erwartung:* Punktestand-Badge steigt **sofort** (synchrone Ledger-Buchung).
- [ ] **[Zeit]** Aufgabe überfällig werden lassen. *Erwartung:* Badge „überfällig" und
      verringerter Wert mit „statt N".
- [ ] Raum anlegen mit Verfallstagen → „+ Aufgabe" am Raum → erledigen.
      *Erwartung:* Heatmap-Kachel wird grün. **[Zeit]** Später grün → amber → rot.
- [ ] **Als Kind:** Aufgabe erledigen geht; „Aufgabe hinzufügen" scheitert mit 403.
      *Erwartung:* verständliche Fehlermeldung — die UI blendet den Block nicht aus.

### Punkte, Belohnungen, Challenge, Marktplatz — `/rewards`, `/challenge`, `/marketplace`
- [ ] Belohnung anlegen → einlösen → als Admin bestätigen. *Erwartung:* Saldo sinkt; bei zu
      wenig Punkten ist „Einlösen" deaktiviert.
- [ ] **Invariante:** Versuchen, mehr auszugeben als vorhanden. *Erwartung:* kein negativer Saldo,
      klare Ablehnung.
- [ ] **[2×]** `/challenge` → „Danke sagen" an das andere Mitglied.
      *Erwartung:* Restkontingent sinkt, Cap bei 10 P pro Woche greift. **[Zeit]** Am Montag
      springt die Wertung auf 0.
- [ ] **[2×]** Marktplatz-Zyklus: anbieten (Escrow) → anderer übernimmt → erledigt → auszahlen.
      *Erwartung:* Punkte landen beim Käufer zusätzlich zu den Basis-Punkten. Auch
      „Zurückziehen" (Refund) testen.
- [ ] **Als Kind:** Marktplatz öffnen. *Erwartung:* 403 — Nav-Link ist sichtbar, die API blockt.

### Einkaufsliste — `/shopping`
- [ ] Liste anlegen, Posten hinzufügen, abhaken → wandert unter „Erledigt". Schnellkatalog und
      „Basics" nutzen. „Reservieren" → Badge „von dir reserviert".
- [ ] **[Gerät]** **Offline-Betrieb** (der wichtigste Test des Moduls): Flugmodus/DevTools-Offline
      → *Erwartung:* Banner „Offline — Änderungen werden synchronisiert…"; Posten abhaken und
      hinzufügen funktioniert weiter. Wieder online → *Erwartung:* alles ist da, nichts doppelt.
- [ ] **[2×]** **LWW-Konfliktarmut:** Gerät A benennt einen Posten um, Gerät B hakt ihn gleichzeitig
      offline ab → beide synchronisieren. *Erwartung:* **beide** Änderungen überleben (die
      zentrale Sync-Invariante, ADR-0032).

### Rezepte & Kochen — `/recipes`, `/recipes/$id/cook`
- [ ] Rezept anlegen, bearbeiten (If-Match), Foto hinzufügen und entfernen.
- [ ] **[Extern]** **Import einer echten Rezept-URL** (z. B. chefkoch.de).
      *Erwartung:* Draft-Review mit erkannten Zutaten; SSRF-Guard lässt öffentliche URLs durch.
      Gegenprobe mit `http://169.254.169.254/` → *Erwartung:* geblockt.
- [ ] Kochmodus: durch die Schritte, Portionen skalieren, Timer starten.
- [ ] **[Gerät]** **Wake-Lock am echten Telefon:** Kochmodus offen lassen.
      *Erwartung:* Bildschirm bleibt an; Touch-Targets sind im Küchenbetrieb bedienbar.
- [ ] Nährwerte-Block am Rezept vorhanden (Auto-Mapping der Zutaten).

### Mahlzeiten — `/mealplan`
- [ ] Zellen füllen (Rezept + Freitext), „Rezept würfeln", „Woche würfeln (Abendessen)".
- [ ] „Einkaufsliste füllen" → auf `/shopping` prüfen. **Nochmal klicken.**
      *Erwartung:* idempotent, keine Duplikate.
- [ ] „Als gekocht markieren" → **[Zeit]** *Erwartung:* das Rezept wird in den nächsten 7 Tagen
      nicht mehr gewürfelt (Wiederholungs-Sperre).
- [ ] Kalender-Abwesenheit in der Woche eintragen → `/mealplan`.
      *Erwartung:* Der Tag ist als „abwesend" markiert (Cross-Modul-Signal).
- [ ] kcal-Ziel + Ausschlüsse setzen → „Woche nach kcal-Ziel füllen".
      *Erwartung:* Badge „im Ziel (±10 %)".

### Kalender & Terminfindung — `/calendar`
- [ ] Termin anlegen (ganztägig, privat, Serie), Serientermin absagen (EXDATE) und verschieben.
- [ ] **[2×]** **Layer-Sichtbarkeit:** Ein `personal`-Termin des anderen Mitglieds.
      *Erwartung:* nicht sichtbar (404) — auch nicht für Admins.
- [ ] ICS-Import: Datei importieren → Meldung mit Zählern. **Dieselbe Datei nochmal.**
      *Erwartung:* alles „übersprungen" (Dedup über UID).
- [ ] **[Extern]** **ICS-Abo im echten Client** (Google/Nextcloud/Apple) — offen seit Phase 5.
      Abo-URL erzeugen und dort eintragen. *Erwartung:* Termine erscheinen — und eine
      **wöchentliche Serie steht über den 29.03. und 25.10. hinweg konstant auf derselben
      Ortszeit** (der Feed trägt seit P9 `TZID` + VTIMEZONE mit echten Übergängen). Das ist der
      eigentliche Test hier; die UTC-Einschränkung von früher ist weg.
      Zusätzlich ein **ganztägiger** Termin: *Erwartung:* er erscheint als ganzer Tag, nicht als
      0-Minuten-Termin um 00:00.
      Danach „Widerrufen" → *Erwartung:* der Client bekommt nichts mehr.
- [ ] **[Zeit]** **DST-Probe:** Wöchentliche Serie „Montag 09:00" über den 29.03. bzw. 25.10.
      hinweg ansehen (Betriebssystem-Zeit umstellen).
      *Erwartung:* bleibt 09:00 Ortszeit.
- [ ] „Freien Termin finden": Dauer eingeben → Vorschläge mit Begründungen („keine Konflikte",
      „in Arbeitszeit") → „Eintragen". *Erwartung:* Termin steht in der Agenda.
- [ ] Cross-Modul: `/shopping` mit vielen offenen Posten → Hinweis „Zeit für einen Einkauf finden?"
      → *Erwartung:* springt nach `/calendar` mit vorbelegtem Titel „Einkauf".
- [ ] **[Extern]** Flag `weather` an → Wetterkarte auf `/calendar` zeigt echte Werte.
      Open-Meteo abklemmen → *Erwartung:* Karte degradiert sichtbar („Wetterdaten gerade nicht
      verfügbar"), kein Crash (Null-Adapter).
- [ ] **[Zeit]** Bei niedriger Erholung (Wearable verbunden) einen Slot ab 90 min suchen →
      *Erwartung:* Begründung „heute wenig erholt". **Gegenprobe:** unter 90 min erscheint sie
      nicht, und die Slot-Liste ist mit und ohne Wearable identisch.

### Zuruf — `/capture`
- [ ] `2 Liter Milch kaufen` → *Erwartung:* Ziel „Einkaufsliste", Label „Milch", Menge „2 l".
      „Übernehmen" → Posten steht auf `/shopping`.
- [ ] `#task Müll rausbringen` → Ziel „Aufgabe" → „Übernehmen" → steht auf `/tasks`.
- [ ] Satz ohne Verb → Ziel „Unsortiert" → *Erwartung:* **kein** „Übernehmen"-Button, nur „Verwerfen".
- [ ] **Aktionskette (braucht laufenden Worker):** `Deo besorgen, dann Bad putzen` → „Übernehmen"
      → Posten auf `/shopping` **abhaken** → *Erwartung:* die vorgemerkte Aufgabe wird auf `/tasks`
      aktiv. Passiert nichts, steht der Outbox-Dispatcher.
- [ ] **Als Kind:** *Erwartung:* 403.

### Briefe, Kommentare, Verknüpfungen — `/letters`, eingebettet
- [ ] **[2×]** Rundbrief schreiben (keine Empfänger anhaken) → als anderes Mitglied lesen.
      *Erwartung:* „ungelesen"-Punkt verschwindet, „Gelesen von 1" steigt. **Im eigenen Browser
      ist dieser Kern-Flow nicht sichtbar** — eigene Briefe gelten nie als ungelesen.
- [ ] „Kümmerst du dich? → Aufgabe" → *Erwartung:* Aufgabe entsteht, der Brief bleibt.
- [ ] Kommentare an allen vier Objekttypen (Anleitung, Rezept, Notiz, Brief): schreiben,
      bearbeiten, löschen. *Erwartung:* an fremden Einträgen keine Bearbeiten-/Löschen-Aktion.
- [ ] Verknüpfung anlegen (Anleitung ↔ Rezept) → *Erwartung:* von **beiden** Seiten sichtbar;
      dasselbe Paar nochmal → idempotent.
- [ ] **Waisen-Reaper (braucht Worker):** Anleitung mit Kommentaren und Verknüpfungen löschen.
      *Erwartung:* nach kurzer Zeit sind auch Kommentare/Links weg.

### Notizen & Anleitungen — `/notes`, `/guides`
- [ ] Notiz anlegen mit „Ans Dashboard pinnen" → *Erwartung:* erscheint auf `/today`.
- [ ] Notiz 6× ändern → *Erwartung:* Versionsliste kappt bei 5. „Wiederherstellen" nutzen und
      wieder rückgängig machen.
- [ ] Notiz löschen → „Papierkorb" → „Wiederherstellen". **[Zeit]** `reap_deleted_job` antriggern
      nach Manipulation von `deleted_at` → *Erwartung:* hart weg.
- [ ] Anleitung anlegen → **Volltextsuche mit deutschem Stemming:** „Fahrrad" eingeben.
      *Erwartung:* findet einen Eintrag, der „Fahrräder" enthält.
- [ ] **[Extern]** Anhang hochladen (braucht konfigurierten Blob-Storage) → Download-Link
      funktioniert → „Entfernen". *Erwartung:* ohne Storage klare Meldung, kein Crash. Datei
      > 25 MiB → *Erwartung:* 413 mit verständlichem Text.

### Tresor — `/vault`
- [ ] Einrichten mit Passphrase → *Erwartung:* Wiederherstellungs-Code wird **einmalig** angezeigt.
- [ ] Eintrag anlegen, aufklappen (on-demand entschlüsselt), bearbeiten.
- [ ] **Seite neu laden** → *Erwartung:* Tresor ist wieder gesperrt (Schlüssel lebt nur im Speicher).
- [ ] **[Gerät]** **Das Krypto-Versprechen selbst:** Netzwerk-Tab öffnen, Eintrag anlegen.
      *Erwartung:* der Request-Body von `POST /v1/vault/items` enthält **weder Name noch Geheimnis
      im Klartext**. Zusätzlich die Konsole auf CSP-Violations prüfen.
- [ ] Recovery-Weg: „Passphrase vergessen?" → Code → entsperren → neue Passphrase setzen.
      *Erwartung:* funktioniert, alte Einträge bleiben lesbar.
- [ ] **Als Kind und als Gast:** *Erwartung:* 403.
- [ ] **[2×] Ungeklärter Pfad — hier genau hinsehen:** Ein **zweites Mitglied** öffnet `/vault`.
      Die Doku beschreibt nicht, wie es an den Haushaltsschlüssel kommt; die UI führt es
      voraussichtlich in den „Tresor einrichten"-Zweig, der einen **neuen** Schlüssel erzeugt.
      *Erwartung — zu klären:* Verliert das erste Mitglied dadurch Zugriff? Das Ergebnis gehört
      als Befund in den BUGLOG oder als Slice in die Roadmap, nicht nur abgehakt.

### Dashboard, Feedback, Recht — `/today`, `/feedback`, `/datenschutz`, `/impressum`, `/neuigkeiten`
- [ ] `/today`: alle sechs Kacheln zeigen echte Daten; jede Kachel springt ins richtige Modul.
- [ ] Auf leerem Haushalt als Admin: „Schnellstart" → Preset „Familie" → *Erwartung:* Räume und
      Aufgaben-Vorlagen sind angelegt.
- [ ] **[Gerät]** **PWA:** Ab dem dritten Besuch erscheint „Als App installieren". Auf Chromium
      installieren; auf iOS „Teilen → Zum Home-Bildschirm". *Erwartung:* App startet
      eigenständig, Icon und Name stimmen. Nach einem echten Deploy: *Erwartung:* Toast „Neue
      Version verfügbar." → „Neu laden".
- [ ] Feedback absenden (mit und ohne Diagnose-Häkchen) → *Erwartung:* erscheint unter „Meine
      Rückmeldungen" **und** in der Ops-Inbox.
- [ ] **[Extern]** Mit gesetztem GitHub-Token: *Erwartung:* ein echtes Issue entsteht im Repo.
- [ ] `/datenschutz`, `/impressum`, `/neuigkeiten` **ohne Login** erreichbar.
      *Erwartung:* Inhalt rendert; der Entwurfs-Hinweis ist sichtbar (juristische Prüfung steht aus).
- [ ] **Datenexport (Art. 15/20).** `/profile` → „Meine Daten exportieren" → ZIP mit dem
      Bordmittel öffnen.
      *Erwartung:* `manifest.json` + `LIESMICH.txt` + `data/*.json`; eigene Notizen sind darin
      wiederzufinden, `users.password_hash` steht als `"<redaktiert>"` da. **[2×]** Ein `member`
      sieht den Haushalts-Knopf **nicht**, und `/v1/household/export` direkt → 403. Volle
      Prüfliste in Abschnitt A.

### Betreiber-Konsole — `ops.<domain>`
- [ ] Login mit Passwort **und TOTP** (Pflicht). *Erwartung:* ohne Code kein Zugang.
- [ ] Operator-Passkey registrieren und damit einloggen.
- [ ] Banner anlegen → *Erwartung:* erscheint im Member-Frontend als ruhige Leiste.
- [ ] Globales Feature-Flag umschalten → *Erwartung:* wirkt im Member-Frontend.
- [ ] Haushalts-Suche → Treffer öffnen → `/audit` → *Erwartung:* der sensible Read ist
      protokolliert (`household.searched` / `household.viewed`).
- [ ] `/operators` → zweiten Operator anlegen und wieder deaktivieren. *Erwartung:* der per CLI
      angelegte Erstoperator steht in der Liste; beide Aktionen erscheinen im Audit-Log; der
      letzte aktive Operator lässt sich **nicht** deaktivieren (kein Lockout).
- [ ] KPI-Dashboard → *Erwartung:* echte Zahlen, sobald reale Haushalte existieren.
- [ ] **Betreiber-Grenze:** *Erwartung:* nirgends in der Konsole sind Fachdaten (Rezepte,
      Nachrichten, Tresor-Inhalte) sichtbar — nur Aggregate.

---

## D — Geräte-/Theme-Matrix

Ersetzt den nicht wiederholbaren Playwright-Lauf vom 2026-07-08 (der vor PWA, Shopping-Fix,
Slice C und dem gesamten CalDAV-Stack lag).

**Zellen:** {mobil (z. B. Pixel 7), desktop} × {hell, dunkel} = 4 Durchgänge.
**Auflagen aus dem BUGLOG:** mindestens ein Durchgang mit **Daten** im Haushalt, mindestens einer
mit **frischem Login**.

Je Route prüfen: Layout bricht nicht · Kontrast reicht (AA) · Tastaturbedienung möglich ·
keine Konsolen-/HTTP-Fehler.

| Route | mobil hell | mobil dunkel | desktop hell | desktop dunkel |
|---|---|---|---|---|
| `/` (Konto) | ☐ | ☐ | ☐ | ☐ |
| `/today` | ☐ | ☐ | ☐ | ☐ |
| `/tasks` | ☐ | ☐ | ☐ | ☐ |
| `/rooms` | ☐ | ☐ | ☐ | ☐ |
| `/rewards` | ☐ | ☐ | ☐ | ☐ |
| `/challenge` | ☐ | ☐ | ☐ | ☐ |
| `/marketplace` | ☐ | ☐ | ☐ | ☐ |
| `/shopping` | ☐ | ☐ | ☐ | ☐ |
| `/recipes` | ☐ | ☐ | ☐ | ☐ |
| `/recipes/$id` | ☐ | ☐ | ☐ | ☐ |
| `/recipes/new` | ☐ | ☐ | ☐ | ☐ |
| `/recipes/import` | ☐ | ☐ | ☐ | ☐ |
| `/recipes/$id/cook` | ☐ | ☐ | ☐ | ☐ |
| `/mealplan` | ☐ | ☐ | ☐ | ☐ |
| `/calendar` | ☐ | ☐ | ☐ | ☐ |
| `/capture` | ☐ | ☐ | ☐ | ☐ |
| `/letters` | ☐ | ☐ | ☐ | ☐ |
| `/notes` | ☐ | ☐ | ☐ | ☐ |
| `/guides` | ☐ | ☐ | ☐ | ☐ |
| `/vault` | ☐ | ☐ | ☐ | ☐ |
| `/feedback` | ☐ | ☐ | ☐ | ☐ |
| `/profile` | ☐ | ☐ | ☐ | ☐ |
| `/security` | ☐ | ☐ | ☐ | ☐ |
| `/login` | ☐ | ☐ | ☐ | ☐ |
| `/register` | ☐ | ☐ | ☐ | ☐ |
| `/child-login` | ☐ | ☐ | ☐ | ☐ |
| `/forgot-password` | ☐ | ☐ | ☐ | ☐ |
| `/reset-password` | ☐ | ☐ | ☐ | ☐ |
| `/verify-email` | ☐ | ☐ | ☐ | ☐ |
| `/datenschutz` | ☐ | ☐ | ☐ | ☐ |
| `/impressum` | ☐ | ☐ | ☐ | ☐ |
| `/neuigkeiten` | ☐ | ☐ | ☐ | ☐ |

**Zusätzlich je Datenroute das Trio:** Empty (leerer Haushalt) · Loading (gedrosseltes Netz) ·
Error (Backend aus oder Netzwerk blockiert). *Erwartung:* jeder Zustand ist sichtbar und
verständlich — nie eine leere Seite, wenn in Wahrheit ein Fehler vorliegt (BUGLOG 2026-07-19).

**Kurz-Durchgang je Rolle:** einmal als Admin, einmal als Mitglied, einmal als Kind.
*Erwartung:* Kinder-Sperren (Tresor, Zuruf, Marktplatz) greifen mit verständlicher Meldung statt
einer rohen 403-Wand — die Nav-Links sind sichtbar, die API blockt. **Im Kalender darf ein Kind
lesen**, aber nicht anlegen/ändern: die Agenda bleibt sichtbar, das Anlegen scheitert mit
verständlicher 403.

---

## E — Oura gegen die echte API

Acht Schritte, einmalig nach der Registrierung einer Oura-OAuth-App durch den Betreiber
(Handgriff in `docs/MODULES/wearables.md`) durchzuführen. Der letzte ist der eigentliche
Grund für diesen Abschnitt: das Feld-Mapping ist gegen die Live-API unverifiziert.

- [ ] **Oura-Verbindung einmal echt durchlaufen** (nach der Registrierung), jetzt komplett über
      die Oberfläche. Flag setzen
      (`UPDATE households SET settings_json = settings_json || '{"wearables": true}'`), dann
      `/profile` → Abschnitt „Wearable" → Datentypen ankreuzen → „Oura verbinden" → bei Oura
      zustimmen.
      *Erwartung:* Rücksprung auf `/profile` mit „Oura ist verbunden."; die angekreuzten Typen
      sind gesetzt. **Gegenprobe in der DB:** `tokens_enc` beginnt mit `v1:` und enthält den Token
      **nicht** im Klartext. **Gegenprobe im Netzwerk-Tab:** keine Antwort trägt einen Token oder
      einen Messwert.
- [ ] **Als zweites Mitglied (auch als Admin) `/profile` öffnen** — *Erwartung:* dort steht die
      eigene Verbindung bzw. gar keine, **nie** die des anderen. Das ist N-2 im Alltag.
- [ ] **Consent widerrufen:** einen Haken entfernen. *Erwartung:* die Werte des Typs sind sofort
      weg (DB gegenprüfen). **Letzten Haken entfernen** → *Erwartung:* die Verbindung ist getrennt,
      die Sektion zeigt wieder den Verbinden-Zustand.
- [ ] **Trennen:** „Verbindung trennen" → Bestätigung nennt die Folge → bestätigen.
      *Erwartung:* Verbindung und alle Werte hart weg, die `consents`-Zeilen bleiben (der Widerruf
      muss auditierbar sein).
- [ ] **Abbruch bei Oura** (dort „Ablehnen" klicken) — *Erwartung:* Rücksprung mit „Du hast die
      Freigabe bei Oura abgebrochen.", keine halbe Verbindung in der DB.
- [ ] **Oura-Feld-Mapping gegen die echte API prüfen** — das ist der eigentliche Grund, warum der
      erste Lauf manuell sein muss. Das Mapping in `backend/app/adapters/oura/client.py` entstand
      aus der dokumentierten v2-Form; niemand hat es je gegen ein echtes Konto laufen lassen.
      Nach dem Verbinden den Ingest-Job antriggern:
      ```bash
      docker compose -f docker-compose.prod.yml exec worker python -c \
        "import asyncio; from app.worker import ingest_wearables_job as j; asyncio.run(j.original_func())"
      ```
      Dann `wearable_daily` ansehen. *Erwartung:* die Werte sind **plausibel** — Schlafdauer in
      Minuten (nicht Sekunden), Ruhepuls in bpm (**nicht** ein 0–100-Score: Ouras
      `daily_readiness.contributors.resting_heart_rate` ist ein Score-Beitrag, wir lesen deshalb
      `sleep.lowest_heart_rate`), Schritte und Kalorien in der richtigen Größenordnung.
      *Falls etwas fehlt:* der Adapter verwirft unplausible Werte bewusst, statt zu klemmen — ein
      Fehlgriff kostet also einen leeren Wert, nie einen falschen. Feldnamen im Adapter korrigieren
      und den Unit-Test `test_wearables_client.py` mitziehen.
- [ ] **Consent-Filter im Alltag prüfen:** einen Typ per `PATCH …/consents` widerrufen, Ingest
      erneut antriggern. *Erwartung:* die zugehörigen Spalten sind **NULL**, die übrigen Werte
      stehen weiter — nicht der alte Wert von gestern.
- [ ] **Retention einmal beobachten:** eine `wearable_daily`-Zeile künstlich altern lassen
      (`UPDATE … SET day = CURRENT_DATE - 100`), dann `reap_wearable_daily_job` antriggern.
      *Erwartung:* die Zeile ist weg, die **Verbindung** steht noch (sie ist kein Messwert).

---

## Befunde

Was hier auffällt, ist **Material**, kein Ärgernis (Prinzip E10):

- Reproduzierbarer Fehler → `docs/BUGLOG.md` (Symptom → Ursache → Fix → Regressionstest → Lehre),
  und wenn möglich ein automatisierter Test, damit die Zeile hier entfallen kann.
- Fehlende Funktion → `KONFIG/Roadmap_to_V0.1.md` bzw. ein Slice.
- Wiederkehrende manuelle Prüfung → prüfen, ob sie ein Gate werden kann. Genau so ist
  `backend/tests/test_compose_env.py` aus Abschnitt A entstanden.
