# BUGLOG

> Jeder nicht-triviale Bug wird hier festgehalten (Prinzip E10: Fehler sind Daten).
> Format pro Eintrag. Wiederkehrende Lehren werden zu Lint-Regeln, Patterns oder
> Checklisten-Punkten befördert.

Eintragsschema:

```
## YYYY-MM-DD — <Kurztitel>  (Modul: <name>, Schwere: niedrig|mittel|hoch)
- **Symptom:** Was war beobachtbar (inkl. Fehler-Referenzcode, falls vorhanden)?
- **Ursache:** Die echte Wurzel, nicht das Symptom.
- **Fix:** Was wurde geändert (Commit/MR)?
- **Regressionstest:** Welcher Test verhindert die Rückkehr (zuerst rot, dann grün)?
- **Lehre:** Was lernen wir? Wird daraus eine Regel/ein Pattern?
```

---

## 2026-10-03 — Worker-Kinder starben alle fünf Sekunden  (Modul: worker, Schwere: hoch)
- **Symptom:** `redis.exceptions.TimeoutError: Timeout reading from redis:6379` aus
  `taskiq_redis/redis_broker.py … brpop`, danach `worker-N is dead. Scheduling reload.` — bei
  leerer Queue alle ~5 s, in dev und prod (14 Neustarts in 60 s gemessen). Der Container blieb
  „healthy" (der Healthcheck pingt nur Redis), und die Outbox lief zwischen zwei Toden weiter:
  nichts sah kaputt aus. Ein Job, der länger als das Fenster lief, wäre mitgestorben.
- **Ursache:** redis-py 8 setzt `socket_timeout` standardmäßig auf 5 s (7.x: kein Timeout); das
  Update kam mit einem Sammel-Bump. `ListQueueBroker.listen` wartet in `BRPOP … 0` — ein Lesen,
  das bei leerer Queue absichtlich nie zurückkehrt. taskiq-redis fängt dort nur
  `ConnectionError`; der `TimeoutError` beendet den Listener und damit den Prozess.
- **Fix:** `build_broker()` in `app/worker.py` baut den Broker mit `socket_timeout=None` (die
  Kwargs reicht taskiq-redis an den Connection-Pool durch). Der Verbindungsaufbau bleibt über
  `socket_connect_timeout` begrenzt.
- **Regressionstest:** `tests/test_worker_broker_idle.py` — lauscht gegen ein echtes Redis länger
  als redis-pys Default und verlangt danach die Zustellung einer Nachricht (vorher rot mit
  `TimeoutError`), plus die Prüfung, dass der Modul-Broker die Einstellung trägt.
- **Lehre:** **Ein Dependency-Bump kann einen Default drehen, den kein Test je berührt hat.** Die
  Suite prüfte `drain_outbox` direkt und nie den Broker im Leerlauf. Und wieder: ein Healthcheck,
  der nur die Abhängigkeit pingt, sagt nichts über den Prozess, den er bewachen soll.

## 2026-10-03 — Ops-Site-Block schaltete Auto-HTTPS ein  (Modul: infra/caddy, Schwere: mittel)
- **Symptom:** Jede Anfrage mit `Host: ops.<domain>` bekam `308 → https://…` — hinter dem
  TLS-terminierenden Proxy eine Umleitungsschleife — und Caddy bestellte ACME-Zertifikate für
  den Platzhalter-Host.
- **Ursache:** Die Site-Adresse war ein nackter Hostname (`ops.localhost, ops.example.com {`).
  Für Caddy heißt das „HTTPS automatisch"; der Kopf derselben Datei sagt „plain HTTP auf :80".
- **Fix:** `http://{$OPS_HOST:ops.localhost} {`; `OPS_HOST` steht in `.env.prod.example` und im
  `environment` des `web`-Service.
- **Regressionstest:** `test_compose_env.py::test_caddy_serves_plain_http_only` und
  `::test_caddy_ops_host_reaches_the_web_container`.
- **Lehre:** Der Member-Block (`:80`) wurde bei jedem Deploy benutzt, der Ops-Block nie durch
  denselben Weg geprüft. Eine Datei, die zwei Dinge gleich behandeln soll, braucht eine Prüfung,
  die über beide läuft.

## 2026-10-03 — Passkey registrierbar, aber nicht zum Anmelden brauchbar  (Modul: accounts/backoffice, Schwere: mittel)
- **Symptom:** Ein Authenticator ohne Resident-Key-Anforderung (z. B. ein Sicherheitsschlüssel)
  registrierte erfolgreich; die Anmeldung endete im Browser mit `NotAllowedError`.
- **Ursache:** Die Anmeldung ist benutzernamenlos (`allowCredentials: []`) — das kann ein
  Authenticator nur mit einem *discoverable* Credential beantworten. Die Registrierung verlangte
  keines (`authenticatorSelection` fehlte), also legten Authenticatoren ein serverseitiges an.
- **Fix:** `registration_options` verlangt `residentKey: "required"`. `preferred` hätte den
  Fehler nur seltener gemacht: ein Schlüssel ohne freien Speicher hätte weiter ein Credential
  registriert, das nie anmelden kann.
- **Regressionstest:** `tests/test_webauthn_options.py`.
- **Lehre:** Der Test-Authenticator (`soft_webauthn`) findet sein Credential immer — er kennt
  den Unterschied nicht. Dieselbe Klasse wie 2026-08-03: ein Helfer, der den Produktionsfall
  nicht erzeugen kann.

## 2026-08-03 — Der stille 401-Replay heilte nur Lesezugriffe  (Modul: web/auth, Schwere: mittel)
- **Symptom:** Die erste **Schreib**-Aktion nach einer Pause schlug sichtbar fehl und funktionierte
  beim zweiten Versuch — bei jedem Ablauf des 15-Minuten-Access-Tokens, also mehrmals täglich.
  Der Refresh war da bereits gelaufen, die Sitzung wieder gültig; nur *diese* Mutation ging
  verloren. TanStack Query wiederholt Mutationen nicht (`retry: 1` gilt nur für Queries), der
  Nutzer sah also einen echten Fehler.
- **Ursache:** `handleResponse` rief `request.clone()`, **nachdem** `fetch` den Body verbraucht
  hatte. Der hey-api-Client reicht dem Response-Interceptor dieselbe `Request`-Instanz, die er an
  `fetch` übergeben hat; deren Stream ist dann *locked and disturbed*, und `clone()` wirft. Für
  GET (kein Body) gelang der Klon — deshalb sah der Mechanismus in Tests und beim Blättern
  vollständig aus. 28 Aufrufstellen im Web schicken einen Body.
  **Zwei Nebenbefunde derselben Datei:**
  (a) `NO_REFRESH_PATHS.some(p => path.includes(p))` ist **Substring**-Matching: `"/login"`
  matchte auch die *authentifizierte* Route `/v1/auth/login-events`, deren 401 damit nie geheilt
  wurde — die Sicherheits-Aktivität auf `/security` fiel nach 15 Minuten stumm aus.
  (b) `EventSource` läuft nicht durch den fetch-Interceptor. Bei einer Nicht-2xx-Antwort gibt der
  Browser **endgültig** auf (`readyState === CLOSED`, kein Auto-Reconnect) — der Live-Kanal blieb
  nach dem ersten 401 den Rest der Sitzung stumm. Der Kommentar im Modul sagte „the browser
  auto-reconnects on drop, so there is no manual retry loop here": richtig für einen Abbruch,
  falsch für den Fall, der wirklich eintritt.
- **Fix:** Der Body wird im **Request**-Interceptor geklont — dem letzten Moment, in dem er
  unversehrt ist — und über eine `WeakMap` an den Response-Interceptor durchgereicht. Der
  Klon-Fallback bleibt für GET und als Rückfallebene. Pfad-Ausnahmen matchen jetzt auf
  **Segmente** (`===` oder Präfix mit `/`) und tragen volle Pfade statt Fragmente. Der
  SSE-Kanal bekommt einen eigenen Reconnect: bei `CLOSED` einmal `renewSession()`, dann neu
  verbinden, mit Backoff und Reset bei `open`; ein *transienter* Abbruch bleibt bewusst dem
  Browser überlassen, sonst liefen zwei Kanäle auf denselben Stream.
- **Regressionstest:** `web/src/test/auth-client.test.ts` von 4 auf 9 Tests, darunter der
  Produktionsfall (ein von `fetch` geleerter POST-Body) und beide Pfad-Ausnahmen;
  `realtime-stream.test.ts` von 4 auf 9, mit permanentem Schluss, transientem Abbruch,
  gescheiterter Rotation, `close()` im Backoff und dem Zurücksetzen bei `open`.
- **Lehre:** **Ein Test-Helfer, der den Produktionsfall nicht erzeugen kann, prüft die Abdeckung
  weg.** `req()` in der alten Testdatei baute nie einen Body — auch der `"POST"`-Fall war bodylos.
  Damit lief der Klon-Pfad ausschließlich gegen einen frischen Request, und der Kommentar
  „a consumed POST body throws -> caught" las sich wie eine Entscheidung statt wie ein täglicher
  Ausfall. Zweitens: **ein `includes` auf einem Pfad ist kein Routen-Vergleich.** Wo Segmente
  gemeint sind, gehören Segmente hin — sonst entscheidet die Zeichenkette, nicht die Route.

## 2026-08-03 — `logout` meldete halb ab, und welche Hälfte, entschied ein Cookie  (Modul: accounts, Schwere: mittel)
- **Symptom:** Kein Fehler, keine Meldung — die Abmeldung sah in jedem Fall vollständig aus
  (204, Cookies weg). Tatsächlich hingen ihre zwei Wirkungen an **zwei verschiedenen Cookies** mit
  verschiedenen Pfaden und Lebensdauern: `custode_rt` (`/v1/auth`, 30 Tage) trieb den
  Postgres-Widerruf, `custode_at` (`/`, 15 min) die Redis-Entwertung.
  **Ohne Access-Cookie** — der Normalfall nach einer Pause, weil es nach 15 Minuten abläuft —
  blieben `access_family:<fam>` und `active_household:<fam>` (30 Tage) stehen.
  **Ohne Refresh-Cookie** blieb `auth_sessions.revoked_at` **NULL**: Redis war verbrannt, die
  Sitzung lebte weiter und liess sich mit dem Refresh-Token jederzeit zurückholen. Das ist der
  ernstere Zweig, weil die Oberfläche „abgemeldet" zeigte.
- **Ursache:** Die Route entschied an der **Repräsentation** (welches Cookie kam an?) statt an der
  Sache (welche Sitzung ist gemeint?). Dieselbe Klasse wie `revoke_all_sessions`, das an der
  Session des Aufrufers statt an „wessen Zeilen sind gemeint" hing (BUGLOG 2026-08-01) — nur eine
  Ebene höher. Auffällig ist der Nachbar: `DELETE /v1/auth/sessions/{family_id}` tut beides
  **unbedingt**, weil die Familie dort ein Parameter ist und nicht aus einem Cookie abgeleitet wird.
- **Fix:** **Eine** Funktion (`service.logout`). Sie leitet die `family_id` aus dem ab, was
  ankommt — vorzugsweise per Nachschlag zum Refresh-Token (der auch ein bereits rotiertes findet),
  sonst aus den Access-Claims — und wirkt dann unbedingt auf **beide** Speicher. Reihenfolge:
  erst Postgres, dann Redis; scheitert danach Redis, lebt höchstens ein Access-Token seine
  Restminuten und ist nicht erneuerbar. Andersherum wäre die Sitzung zurückholbar.
- **Regressionstest:** zwei neue in `test_auth_http.py`, je einer für die asymmetrische Richtung,
  beide zuerst rot (per `git stash` verifiziert):
  `test_logout_with_only_the_refresh_cookie_still_burns_the_access_tokens` und
  `test_logout_with_only_the_access_cookie_still_revokes_the_session`. Der zweite prüft die
  Wirkung dort, wo sie wehtut: das Refresh-Token darf die Sitzung **nicht** zurückholen können.
- **Lehre:** **Wenn zwei Speicher denselben Zustand tragen, darf nicht die Anwesenheit eines
  Clients entscheiden, welcher davon aufgeräumt wird.** Und: getestet waren vorher genau die
  beiden *symmetrischen* Fälle — „beide Cookies da" und „gar keine". Eine Matrix mit vier Feldern,
  von der zwei geprüft sind, sieht in der Testliste vollständig aus.

## 2026-08-03 — Ein erledigter, aber nicht abgerechneter Kauf ließ den ganzen Austritt scheitern  (Modul: marketplace, Schwere: hoch)
- **Symptom:** Keins im Betrieb — gefunden bei der Bestandsaufnahme zum Phase-11-Plan, adversarial
  gegengeprüft (Urteil: bestätigt). Wer als **Käufer** ein `accepted` Listing hält, dessen
  Task-Instanz bereits `done` ist, und dann austritt, dessen `member.left`-Handler wirft
  `invalid_state` (409), fünf Zustellversuche, DLQ. Da alle drei Schritte des Austritts **eine**
  Transaktion teilen (`app/member_exit.py`), lief danach *nichts*: Escrow blieb auf
  `escrow:<listing_id>` gesperrt, offene Verkäufe derselben Person blieben stehen, Aufgaben blieben
  zugewiesen, der Restsaldo verfiel nicht. Die Mitgliedschaft war beendet, die Ökonomie nicht.
  Bei der **Haushalts-Auflösung** war der Schaden größer: dort fährt `settle_household_dissolution`
  **alle** Mitglieder in einer Transaktion (bewusst, weil `revert_listing` den Verkäufer
  kreditiert). Ein einziges solches Listing ließ die Abwicklung des gesamten Haushalts scheitern.
- **Ursache:** `release_positions_of` wickelte **jeden** angenommenen Kauf über `revert_listing`
  zurück, und das ruft `tasks.api.reassign_instance`, das eine nicht mehr offene Instanz mit 409
  ablehnt. Die Annahme dahinter — „ein angenommener Kauf ist unerledigt" — hält nicht, weil es
  **kein Auto-Settle gibt**: `settle_listing` hat genau einen Aufrufer, den Knopf „Auszahlen" im
  Web. Der Zustand *erledigt, aber nicht abgerechnet* ist damit kein Randfall, sondern der
  Normalfall zwischen zwei Klicks — `test_marketplace_http.test_full_escrow_lifecycle` durchläuft
  ihn selbst, ohne ihn zu prüfen. Zweiter Pfad derselben Klasse: eine getombstonete Instanz ließ
  `get_instance` 404 werfen, mit demselben Ausgang.
- **Fix:** `release_positions_of` verzweigt am **Begriff** statt am Zustand des Listings: hat der
  Käufer geliefert (`done`), wird **abgerechnet** — wer die Arbeit gemacht hat, hat verdient, und
  dass er gerade geht, ändert daran nichts (sein Saldo verfällt danach ohnehin als eigene Buchung,
  Schritt 3, und deshalb steht der zuletzt). Sonst wird rückabgewickelt. Die naheliegende Rettung
  „Escrow einfach an den Verkäufer" wäre falsch gewesen: der hätte die erledigte Aufgabe **und**
  seine Punkte zurückbekommen. `revert_listing` bekommt den Vertrag „nicht geliefert" (409 bei
  `done`) und toleriert eine getombstonete Instanz — zurückzugeben ist dann nichts, aber das
  Escrow muss trotzdem los. Neue Naht `tasks.api.instance_status` → `str | None`, damit der
  Aufrufer **fragen** kann, statt einen 404 als Kontrollfluss zu fangen.
- **Regressionstest:** vier, jeder zuerst rot (verifiziert per `git stash` des Fixes):
  `test_member_exit_economy.py::test_exit_survives_a_bought_task_that_is_already_done`,
  `…::test_a_delivered_task_pays_the_buyer_not_the_seller` (die Gegenprobe — der Verkäufer bekommt
  sein Escrow **nicht** zurück; ohne sie ginge die falsche Rettung grün durch),
  `…::test_exit_survives_a_bought_task_that_was_deleted`, und
  `test_household_dissolution.py::test_the_settlement_survives_a_delivered_but_unsettled_trade`,
  der erst das Vorher zeigt (Escrow gebunden) und dann beweist, dass Schritt 3 überhaupt erreicht
  wird.
- **Lehre:** **Ein Ablauf, der als Reaktion auf ein Ereignis läuft, muss für jeden Zustand total
  sein, den seine Fachdaten annehmen können.** Der Austritt ist keine Anfrage, die man wiederholen
  kann — er hat keinen Benutzer, der einen 409 liest, und keine Oberfläche, die ihn anzeigt. Sein
  einziger Leser ist eine DLQ, in die bis heute niemand schaut (eigener Roadmap-Punkt).
  Zweitens, und das ist die schon bekannte Klasse: **wer eine Zustandsprüfung aus einem
  Nachbarpfad übernimmt, übernimmt auch dessen Annahmen.** `reassign_instance` verlangt `open`,
  weil es für den *Kauf* gebaut wurde; der *Austritt* hat diese Vorbedingung nie gehabt.

## 2026-08-02 — Die Rotation schrieb einen Merkzettel fort, den die Datenbank längst widerrufen hatte  (Modul: accounts, Schwere: hoch)
- **Symptom:** Keins im Betrieb — benannt beim adversarialen Durchgang zu 11-S1e und als eigener
  Punkt in die Roadmap gestellt, weil er jeden Anmeldeweg berührt. `POST /v1/auth/refresh` mintete
  das neue Access-Token mit genau dem, was in Redis unter `active_household:<family>` stand: dem
  Haushalt **und der Rolle**. Geprüft wurde davon nichts.
- **Ursache:** Der Merkzettel ist eine **Repräsentation** des Scopes, keine Berechtigung — und
  gesetzt hat ihn die betroffene Person selbst, per Haushaltswechsel oder beim Login. Er hält so
  lange wie das Refresh-Token: **30 Tage.** Der Anmeldeweg daneben tut es richtig
  (`switch_household` fragt `get_active_role`, der Login `resolve_sole_household` — beide gegen die
  Datenbank, beide mit `deleted_at`-Filter auf Mitgliedschaft **und** Haushalt); nur die Rotation
  glaubte ihrem Cache.
  Zwei Wege führten hinein:
  **(1) Der Rollenwechsel, ohne jedes Rennen.** `change_role` widerruft — anders als
  `remove_member` — keine Sitzungen. Ein herabgestufter Admin behielt seine Admin-Rolle also nicht
  fünfzehn Minuten, sondern **unbefristet**: jede Rotation schrieb sie neu fort. Das ist der
  ernstere der beiden, weil er deterministisch ist und keinen Zufall braucht.
  **(2) Der Zustand nach dem Fenster in 11-S1e.** `remove_member` und `dissolve_household`
  widerrufen die Sitzungen in einer eigenen `maint`-Transaktion, die **vor** der äußeren committet.
  Wer sich in diesem Fenster anmeldet, hält danach eine lebende Sitzung samt Merkzettel auf einen
  Haushalt, in dem er nicht mehr Mitglied ist — und rotiert sie weiter.
- **Fix:** `service.resolve_refresh_scope` leitet Haushalt **und** Rolle je Rotation aus der
  Datenbank ab; der zwischengespeicherte Wert nennt nur noch den Haushalt und gilt als Hinweis.
  `get_active_role` trägt die Bedingung bereits (lebende Mitgliedschaft **und** lebender Haushalt),
  also entstand keine zweite Wahrheit daneben. Fällt der Scope weg, wird auch der Merkzettel
  geräumt, damit `/me` und Redis nicht auseinanderlaufen. Bewusst **kein** Auto-Scope auf eine
  einzige Mitgliedschaft: eine Rotation darf einen Scope bestätigen, keinen neuen vergeben.
  Dazu `change_role`: es entwertet jetzt die **Access-Tokens** der betroffenen Person
  (`burn_access_tokens`), nicht ihre Sitzungen — sie bleibt Mitglied, nur ihre Rechte ändern sich.
  Dafür entstand `access.revoke_access_tokens`, das den Merkzettel **stehen lässt**;
  `revoke_access_family` hätte ihn mitgelöscht und die Person nach einer Herabstufung ohne
  Haushalts-Kontext dastehen lassen.
- **Regressionstest:** `tests/test_refresh_rescope.py`, zehn Fälle. Jeder zeigt erst das Vorher
  (die Rotation *trägt* den Scope), dann den Vorgang, dann das Nachher — und das Nachher ist eine
  **Wirkung**, kein Feld: geprüft wird über eine RLS-gescopte Route, denn `/v1/auth/me` liest nur
  dasselbe Token zurück, das schon in der Rotationsantwort steht. Dazu die Gegenproben (ein
  unbeteiligtes Mitglied rotiert unverändert; eine **Beförderung** kommt genauso schnell an wie
  eine Herabstufung) und ein Test gegen den **echten** Entfernen-Endpunkt, damit die Prämisse des
  Slices nicht bloß behauptet ist. Negativprobiert in drei Schritten: ohne die DB-Ableitung sind
  7 von 8 rot; ohne den Token-Burn genau die zwei Fälle, die ihn brauchen (in einer vollen Suite
  von ~850 Tests **nur** diese zwei); und der Redis-Zweig hat einen eigenen Fall.
- **Zwei Funde am eigenen Code, beide aus dem adversarialen Durchgang und beide vor dem Merge:**
  **(1)** Das Räumen des Merkzettels hing an `scope is None` — und `get_active_household` ist
  fail-closed, liefert bei einem Redis-**Lesefehler** also dasselbe `None` wie bei „kein
  Merkzettel". **Ein einziger Aussetzer hätte einen gültigen Haushalts-Kontext dauerhaft
  gelöscht**, aus einer Störung von Sekunden einen bleibenden Verlust. Geräumt wird jetzt nur,
  wenn die Datenbank die zwischengespeicherte Zuordnung *ausdrücklich* abgelehnt hat
  (`cached is not None and scope is None`).
  **(2)** Der Test für den aufgelösten Haushalt begründete sich mit „dem Zustand nach dem Rennen
  aus 11-S1e" — falsch: `households.deleted_at` hat genau einen Schreiber, und der tombstonet die
  Mitgliedschaften in derselben Transaktion; „Haushalt tot, Mitgliedschaft lebt" ist unerreichbar.
  Der Test bleibt (der Zweig in `get_active_role` ist bewusst eigenständig, ADR-0085 §6), sagt
  aber jetzt, was er wirklich prüft. Eine Begründung, die nicht stimmt, ist schlimmer als keine.
- **Lehre:** Der fünfte belegte Fall derselben Klasse — **eine Prüfung, die an einer Repräsentation
  hängt, prüft den Begriff nicht.** Neu daran ist die Form: hier war die Repräsentation ein
  *Cache*, und ein Cache sieht nicht wie eine Autorisierungsentscheidung aus. Der Prüfpunkt bleibt
  derselbe: *wer kann den Wert setzen, und wie lange hält er?* Setzbar von der begünstigten Person,
  haltbar dreißig Tage — das ist kein Cache, das ist eine Vollmacht.
  Zweite, kleinere Lehre: **wer Rechte entzieht, muss auch prüfen, dass er sie vergeben kann.** Ein
  Fix, der nur Herabstufungen durchreicht, führte eine zweite Wahrheit ein — die geltende Rolle
  hinge davon ab, in welche Richtung sie sich zuletzt bewegt hat. Deshalb hat der Beförderungsfall
  einen eigenen Test.

---

## 2026-08-01 — Eine Rolle ist kein Kontotyp: die Auflösung wurde fast zur Konto-Vernichtung  (Modul: accounts, Schwere: hoch)
- **Symptom:** Keins im Betrieb — der Fund kam aus dem adversarialen Durchgang **vor** dem Merge
  von 11-S1e. Die Haushalts-Auflösung merkte jede Mitgliedschaft mit `role == 'child'` als **Konto**
  zur endgültigen Löschung vor.
- **Ursache:** `child` ist eine *Mitgliedschafts*-Rolle, kein Kontotyp. Ein Admin kann jedes
  Mitglied per `PATCH /v1/household/members/{id}` auf `child` herabstufen — die Oberfläche bietet
  die Rolle offen an, `change_role` prüft nur die Admin-Kontinuität. Zwei Aufrufe genügten also:
  herabstufen, auflösen. Das Opfer war ab dem Commit ausgesperrt (`_reject_deleted`), es gibt
  **keine Route, die einen Löschantrag zurücknimmt**, und nach 30 Tagen räumt der Purge das Konto
  aus — samt der Mitgliedschaften in **allen anderen** Haushalten. Aus einer Verwaltungsbefugnis
  wäre eine Konto-Vernichtungs-Primitive geworden.
- **Warum es plausibel aussah:** Der Tombstone ist für echte Kinder-Konten *richtig* — sie haben
  kein Login außerhalb des Haushalts und wären sonst unerreichbar und von keinem Löschjob
  erfassbar. Die Begründung stimmt; nur war „Rolle == child" ein **Stellvertreter** für die
  Eigenschaft, die sie trägt, und der Stellvertreter ist vom Angreifer setzbar.
- **Fix:** `_account_dies_with_this_household` prüft die Eigenschaft selbst — (1) kein eigener
  Anmeldeweg (`email` und `password_hash` beide NULL, genau das legt `create_child` an) und (2)
  keine weitere lebende Mitgliedschaft. Ein Konto mit E-Mail kann sich per Passwort-Reset
  zurückholen; eines ohne kann es nicht. Das ist der Unterschied, um den es geht.
- **Regressionstest:** `test_an_adult_demoted_to_child_keeps_their_account` und
  `test_a_child_account_with_another_household_survives`. Negativprobiert: ohne die Prüfung sind
  beide rot.
- **Lehre:** **Eine Autorisierungsentscheidung muss die Eigenschaft prüfen, die sie rechtfertigt —
  nicht einen Stellvertreter dafür.** Und der Prüfpunkt: *Wer kann diesen Stellvertreter setzen?*
  Ist es dieselbe Person, die von der Entscheidung profitiert, ist es kein Kriterium, sondern ein
  Hebel. Verwandt mit ADR-0083 („RLS schützt Zeilen, nicht Aussagen") — auch dort war die Frage,
  ob die Grenze am Begriff hängt oder an einer zufälligen Repräsentation.

---

## 2026-08-01 — Ein Teilschritt committete vor dem Ganzen und überlebte dessen Rollback  (Modul: accounts, Schwere: hoch)
- **Symptom:** Ebenfalls vor dem Merge gefunden. Die Auflösung setzte die Kinder-Tombstones in
  einer **eigenen** Session, die beim Verlassen des Kontextmanagers sofort committete — während
  Haushalts-Tombstone, Mitgliedschaften und beide Outbox-Ereignisse noch in der Transaktion der
  Session-Dependency hingen.
- **Ursache:** Der RLS-Guard auf `users` (`id = app.user_id`) verlangt eine andere Identität als
  die des handelnden Admins, und die naheliegende Antwort darauf ist eine zweite Session. Die hat
  aber eine eigene Transaktionsgrenze. Rollt die äußere danach zurück — im Router genügt ein
  Redis-Ausfall im anschließenden `burn_access_families` —, bleibt ein **lebender** Haushalt mit
  Konten stehen, die zur endgültigen Löschung vorgemerkt sind. Unwiderruflich, unbemerkt, und die
  Kinder können es selbst nicht sehen.
- **Warum die Begründung im Kommentar falsch war:** Sie war von `revoke_all_sessions` übernommen
  („wir fehlen Richtung mehr Löschung"). Dort kostet ein Fehlschlag eine erneute Anmeldung. Hier
  kostet er ein Konto. **Dieselbe Formel, ein anderer Einsatz.**
- **Fix:** `set_config('app.user_id', …, true)` — transaktionslokal, beliebig oft umschaltbar,
  danach auf den Actor zurückgesetzt. Der Tombstone liegt damit in **derselben** Transaktion, die
  Grenze zieht weiterhin die Datenbank, und alles-oder-nichts bleibt erhalten.
- **Regressionstest:** `test_a_rollback_leaves_no_account_marked_for_deletion` — löst auf, rollt
  zurück, prüft, dass **nichts** übrig ist.
- **Lehre:** **Eine Begründung, die für einen Schritt gilt, gilt nicht automatisch für den
  Nachbarn.** „Wir fehlen in die sichere Richtung" ist keine Konstante, sondern hängt am Einsatz —
  und wer sie kopiert, muss den Einsatz neu bestimmen. Praktisch: ein Teilschritt mit anderem
  RLS-Scope gehört über `set_config(..., true)` in dieselbe Transaktion, nicht in eine zweite
  Session.

---

## 2026-08-01 — Ein entferntes Mitglied behielt seine Sitzungen  (Modul: accounts, Schwere: hoch)
- **Symptom:** Keins im Vordergrund. `DELETE /v1/household/members/{id}` antwortete 204, die
  Mitgliedschaft war getombstonet, `member.left` lag in der Outbox — und die Sitzungen der
  entfernten Person lebten weiter. Gefunden beim adversarialen Durchgang zu Slice A, dem Slice,
  der die **Oberfläche** zu dieser Route gebaut hat; im Betrieb war die Route bis dahin nie
  aufrufbar.
- **Ursache:** `revoke_all_sessions(session, user_id=…)` bekam die Session des **Aufrufers**.
  `auth_sessions` trägt `FORCE ROW LEVEL SECURITY` mit dem Prädikat
  `user_id = current_setting('app.user_id')` (Migration 0005), und `get_session` setzt
  `app.user_id` auf den handelnden Admin. SELECT und UPDATE trafen also **null Zeilen** — still,
  ohne Fehler, mit `set()` als Rückgabe. `burn_access_families(set())` war damit ein No-op.
  Von vier Aufrufern passte das Prädikat bei dreien **zufällig**, weil dort die betroffene Person
  die aufrufende ist (Passwort-Reset, Kontolöschung, Selbst-Austritt). Nur beim Entfernen durch
  einen Admin fielen sie auseinander.
- **Warum es teurer ist als „15 Minuten":** nicht nur das Access-Token überlebte. Die
  **Refresh-Familie** blieb ebenfalls gültig, und `refresh` mintet das neue Access-Token mit
  `household_id`/`role` aus **Redis** (`get_active_household`), nie gegen die Datenbank. Ein
  entferntes Mitglied konnte seinen Zugriff auf genau den Haushalt, aus dem es entfernt wurde,
  rollierend über die Lebensdauer des Refresh-Tokens verlängern.
- **Warum es niemand sah:** 11-S1a hatte einen Test für den Sitzungs-Widerruf — für den
  **Selbst**-Pfad. Genau der, bei dem das Policy-Prädikat zufällig passt. Der Docstring desselben
  Tests warnte davor, dass „geteilt" kein Beweis für „verdrahtet" ist; die Warnung galt eine Ebene
  höher, als sie geschrieben war. Und der Bestätigungstext im neuen Web-Dialog behauptete „Der
  Zugang endet sofort".
- **Fix:** `revoke_all_sessions` nimmt **keine Session mehr entgegen** und öffnet eine eigene
  `maint_session()` (`custode_maint` hat `maint_all` + DML auf `auth_sessions` seit Migration
  0005 — keine Migration nötig). Damit ist die Falle entfernt statt an einer Stelle umgangen. Die
  eigene Transaktion committet **vor** der des Aufrufers: bricht der Aufrufer ab, ist jemand
  ausgeloggt, der Mitglied bleibt — wir fehlen Richtung weniger Zugriff.
- **Regressionstest:** `test_removal_by_an_admin_revokes_the_sessions_too` — bewusst als Zwilling
  neben `test_leaving_revokes_every_live_session` gestellt, damit der Unterschied zwischen den
  beiden Pfaden im Test sichtbar ist. Zuerst rot (2 lebende Sitzungen vorher, 2 nachher, leere
  Familienmenge), nach dem Fix grün.
- **Lehre:** **Ein RLS-Prädikat, das die handelnde Person nennt, ist keine Mandantengrenze — es
  ist eine Selbstbezüglichkeit.** Wo eine Funktion auf *fremde* Zeilen wirkt, darf sie die Session
  des Aufrufers nicht benutzen; die Signatur muss das erzwingen, nicht ein Kommentar.
  Verwandt mit ADR-0083 („RLS schützt Zeilen, nicht Aussagen") und mit der Reaper-Lehre: eine
  Operation, die bei 0 Treffern genauso aussieht wie bei Erfolg, braucht einen Test, der das
  Vorher beweist — und zwar auf **jedem** Pfad, nicht auf dem bequemsten.

---

## 2026-08-01 — Zwei gleichzeitige Austritte ließen den Haushalt ohne Verwaltung  (Modul: accounts, Schwere: mittel)
- **Symptom:** Zwei Admins, die im selben Moment austreten, kommen beide durch. Danach hat der
  Haushalt **null** Admins — und weil sowohl Einladungen als auch Rollenwechsel `AdminPrincipal`
  verlangen, gibt es keinen Weg heraus. Dasselbe mit Austritt gegen Selbst-Herabstufung.
- **Ursache:** Die Admin-Kontinuität ist eine Invariante über **mehrere** Zeilen, geprüft von drei
  Funktionen (`change_role`, `remove_member`, `leave_household`). Alle drei lasen den Bestand mit
  einem gewöhnlichen SELECT; die Engine setzt kein `isolation_level`, es gilt also READ COMMITTED.
  Zwei Transaktionen sahen einander schlicht nicht. Die Invariante stand als **hart** in
  `modules/accounts/CLAUDE.md` und hatte keine Entsprechung in der Datenbank.
- **Warum jetzt:** vorher brauchte es zwei Admins, die gleichzeitig gegeneinander handeln —
  theoretisch, weil es für `change_role`/`remove_member` überhaupt keine Bedienoberfläche gab.
  Slice A baut sie. Jetzt reicht, dass zwei Mitbewohner dasselbe wollen.
- **Fix:** `_locked_roster` — eine Stelle, die die lebenden Mitgliedschaften des Haushalts mit
  `FOR UPDATE` liest, `ORDER BY id` für eine deterministische Sperrreihenfolge. Alle drei
  Funktionen benutzen sie.
- **Regressionstest:** `test_two_admins_leaving_at_once_cannot_empty_the_household` — zwei
  `leave_household` über `asyncio.gather`. Formuliert über die **Wirkung** (≥ 1 Admin bleibt),
  nicht über die Sperre; wer von beiden gewinnt, darf sich ändern. Negativprobe durchgeführt:
  ohne `FOR UPDATE` bleiben 0 Admins übrig.
- **Lehre:** **Eine Invariante über mehrere Zeilen, die nur im Anwendungscode geprüft wird, ist
  unter READ COMMITTED keine Invariante.** Entweder eine Sperre über genau die Zeilen, die sie
  ausmachen, oder eine DB-Bedingung. Und: eine Race Condition wird nicht dadurch harmlos, dass
  bisher keine Oberfläche sie auslösen konnte — sie wartet nur auf die Oberfläche.

---

## 2026-07-31 — Der Retention-Reaper lief seit Phase 9 jede Nacht ins Leere  (Modul: kernel/worker, Schwere: hoch)
- **Symptom:** Keins im Vordergrund — genau das ist der Punkt. Der tägliche 03:00-Cron
  (`reap_deleted_job`) meldete nichts, weil er auch bei Erfolg nur bei `total > 0` loggt. In der
  Datenbank blieb jede getombstonete Zeile liegen. Gefunden bei der Bestandsaufnahme für die
  Löschkaskade (Art. 17), nicht im Betrieb.
- **Ursache:** `_RETENTION_TABLES` (`app/worker.py`) wuchs in Phase 9 von `("notes",)` auf drei
  Tabellen. Die Rechte wuchsen nicht mit: `external_calendar_subscriptions` hatte die
  `maint_all`-Policy (Migration 0065), aber nur `GRANT SELECT` — kein DELETE; `calendar_events`
  hatte weder Policy noch irgendeinen Grant für `custode_maint` (Migration 0032 vergibt nur an
  `custode_app`). **Postgres prüft Tabellenrechte beim Planen, nicht beim Treffer** — der Job
  scheiterte also mit `permission denied`, unabhängig davon, ob überhaupt Zeilen fällig waren. Und
  weil `reap_deleted` alle Tabellen in **einer** Transaktion abarbeitete, riss der Fehler den
  `notes`-Purge mit, der für sich genommen einwandfrei funktioniert hätte. Reproduziert gegen
  PG 18: `SELECT=True/DELETE=False` bzw. `SELECT=False/DELETE=False`, Lauf bricht mit
  `InsufficientPrivilegeError` ab, `notes` allein läuft durch.
- **Warum es niemand sah:** die Reaper-Tests riefen `reap_deleted(..., tables=("notes",))` mit
  einem **Literal** auf. `_RETENTION_TABLES` kam in keinem Test vor. Die Liste behauptete etwas
  über die Datenbank, und nichts prüfte die Behauptung.
- **Fix:** Migration `0071_retention_grants` zieht je Tabelle genau das nach, was fehlt (Policy nur
  dort, wo sie fehlte — der Downgrade nimmt sonst die Arbeit von 0065 mit zurück). `reap_deleted`
  arbeitet jetzt **eine Transaktion je Tabelle** ab, protokolliert eine scheiternde Tabelle und
  macht weiter; `RetentionResult.failed` trägt sie nach oben, damit ein Ausfall alarmierbar ist
  statt wie „nichts zu tun" auszusehen.
- **Regressionstest:** `tests/test_retention_grants.py` prüft **jede** Tabelle aus
  `_RETENTION_TABLES` gegen die echte Datenbank — SELECT- und DELETE-Recht, `maint_all`-Policy,
  `deleted_at`-Spalte, und führt die echte Purge-Anweisung aus. Ohne Migration 0071 rot mit genau
  den beiden Tabellennamen. Dazu in `tests/test_retention_reaper.py` ein Test, dass eine gesperrte
  Tabelle den Rest nicht mitreißt — ohne die Transaktions-Umstellung rot.
- **Lehre:** **Eine Liste, die etwas über die Datenbank behauptet, muss gegen die Datenbank geprüft
  werden — nicht gegen sich selbst.** Das ist dieselbe Klasse wie BUGLOG 2026-06-17 („grünes CI,
  rotes Prod": Settings, die keine Compose-Datei durchreicht) und der Grund, warum
  `test_compose_env.py` und `test_export_policy.py` existieren. Zweite Lehre: **ein Job, der nur
  bei Erfolg mit Wirkung loggt, ist im Fehlerfall stumm.** Der Reaper meldete drei Wochen lang
  nichts und niemandem fiel etwas auf.

## 2026-07-30 — Origin-Lock in `kernel/fetch` griff nur für Basic-Auth  (Modul: kernel, Schwere: hoch)
- **Symptom:** Keins. Gefunden bei der Sicherheitslupe über den Wearables-Slice, bevor der erste
  Bearer-Aufrufer live ging — der Fehler wäre erst mit dem Google-CalDAV-Adapter scharf geworden.
- **Ursache:** `safe_request` sperrt Redirects auf die Ursprungs-Origin, sobald Zugangsdaten im
  Spiel sind. Das Gate hing an `if auth is not None` — also an der **Repräsentation** „Basic-Tupel",
  nicht am Begriff „Credential". Als P9 `bearer=` als eigenen Parameter einführte, war der neue
  Parameter vom Lock schlicht nicht erfasst: ein bösartiger CalDAV-Server hätte mit einem 302 auf
  einen fremden Host das OAuth-Bearer-Token eingesammelt. Bei einem Bearer wiegt das schwerer als
  bei Basic — er ist reines Inhaberrecht **ohne jede eigene Origin-Bindung**, wer ihn hat, ist wer.
- **Fix:** Bedingung auf `auth is not None or bearer is not None` erweitert (`kernel/fetch.py`);
  Modul-Docstring und ADR-0079 §7 sprachen ebenfalls nur von Basic und wurden nachgezogen; die
  Invariante steht jetzt als Nachtrag in ADR-0030, wo der Guard beschlossen wurde.
- **Regressionstest:** `backend/tests/test_fetch_ssrf.py` — Redirect auf fremde Origin **mit**
  `bearer=` muss abbrechen. Zuerst rot (das Token folgte dem Redirect), dann grün.
- **Lehre:** **Ein Sicherheits-Gate an einem Begriff festmachen, nicht an einer Repräsentation.**
  „Wenn eine Credential dabei ist" bleibt richtig, wenn eine zweite Credential-Form dazukommt;
  „wenn `auth` gesetzt ist" fällt dann still auf. Übertragbar auf jede Prüfung, die heute genau
  eine Ausprägung eines Konzepts kennt. Als Auflage in ADR-0030 festgehalten: Credentials gehören
  an `auth=`/`bearer=`, nie von Hand in `headers` — dort sieht der Guard sie nicht.

## 2026-07-30 — OAuth-Callback war an den Flow gebunden, nicht an den Browser  (Modul: wearables, Schwere: hoch)
- **Symptom:** Keins — die Lücke war im Betrieb unsichtbar und wurde bei der Entwurfsprüfung für
  den Google-CalDAV-Slice gefunden (adversariale Sicherheitslupe), bevor sie je live ging.
- **Ursache:** Der Callback (`modules/wearables/router.py`) vertraute ausschließlich dem
  single-use `state`. Der authentifiziert aber den **Flow**, nicht den **Browser**: Angreifer
  startet einen eigenen Connect, schickt die Authorize-URL an eine andere Person, diese stimmt
  mit **ihrem** Oura-Konto zu — und ihre Tokens landen in der Zeile des Angreifers. Der
  Ingest-Cron zieht dann ihre Gesundheitsdaten unter `member_id = Angreifer` ein, der sie als
  „eigene" liest. Bei Art.-9-Daten ist das eine Verletzung, keine Unbequemlichkeit.
  Der Rollen-Recheck half nicht: er prüft die Rolle des *Initiators*, nicht wer den Browser
  fährt. Mein eigener Docstring trug sogar die falsche Begründung („there is no authenticated
  principal on this request") — tatsächlich ist das Access-Cookie `SameSite=Lax` mit `path=/`
  und wird bei der Top-Level-GET-Navigation vom Provider **mitgeschickt**.
  **Zweiter Fund am selben Ort:** `state.py` las mit `GET` und löschte mit `DELETE` — zwei
  Kommandos. Zwei gleichzeitig eintreffende Callbacks lesen beide das Payload, bevor einer
  löscht; „single-use" hieß in Wahrheit „zweimal nutzbar".
- **Fix:** Neue Kernel-Naht `peek_access_user_id(request)` — liest das Access-Cookie, **ohne**
  einen Principal zu binden oder zu werfen (der Callback nimmt seinen RLS-Scope weiter aus dem
  state, und eine abgelaufene Session soll einen freundlichen Redirect bekommen, kein 401). Der
  Callback verlangt jetzt `browser_user_id == pending.user_id`; fehlende Session zählt als
  Nichtübereinstimmung, weil ein nicht zuordenbarer Grant nicht angenommen werden darf. Beide
  Fälle antworten identisch, damit die Antwort nicht verrät, ob ein state existierte.
  `pop_state` nutzt `GETDEL` (ein Roundtrip, Redis 6.2+).
- **Regressionstest:** `test_a_foreign_browser_cannot_complete_my_flow` (der Angriff Ende zu Ende:
  Angreifer startet, Opfer-Browser ruft den Callback — nichts entsteht, der Code wird nicht
  einmal getauscht), `test_a_session_less_browser_cannot_complete_a_flow`,
  `test_state_is_consumed_atomically` (zwei gleichzeitige Callbacks → genau einer gewinnt).
  **Negativprobiert:** ohne den Guard schlagen die ersten beiden fehl, der Angriff geht also durch.
  Dazu `test_no_token_or_code_reaches_the_logs` mit neuer `captured_logs`-Fixture.
- **Lehre:** (1) Ein `state` authentifiziert einen **Vorgang**, nie einen **Aufrufer** — wer einen
  OAuth-Callback absichert, braucht beides: state *und* Browser-Bindung. (2) „Unauthentifiziert"
  ist nicht dasselbe wie „blind": dass eine Route keinen Login **erzwingt**, heißt nicht, dass sie
  die vorhandene Session ignorieren muss. (3) Single-use über zwei Redis-Kommandos ist kein
  Single-use. (4) **Ein Docstring ist keine Zusicherung:** dieses Modul behauptete „no token ever
  reaches a response or a log", getestet war nur die Response. Die neue `captured_logs`-Fixture
  macht solche Sätze prüfbar — ein `grep` über die Suite fand vorher **null** Log-Assertions.

## 2026-07-26 — CalDAV auf Prod still halb tot: `CUSTODE_CRYPTO_KEY` erreichte den Container nie  (Modul: infra/calendar, Schwere: hoch)
- **Symptom:** Nach dem Deploy des kompletten CalDAV-Stacks (#133/#143/#145/#146/#147) hätten
  Abos **mit Zugangsdaten** auf dem Produktionsserver durchweg `503 crypto_unconfigured` geantwortet und jeder
  15-Minuten-Cron-Tick hätte `last_sync_error='crypto_unconfigured'` gesetzt. Anonyme Abos syncen
  weiter — der Fehler wäre **still** geblieben, ohne Crash und ohne Log-Auffälligkeit. Gefunden
  beim Planungs-Audit vor Phase-9-Fortsetzung, nicht im Betrieb.
- **Ursache:** `docker-compose.prod.yml` reichte `CUSTODE_CRYPTO_KEY` in keinem
  `environment:`-Block durch, und `.env.prod.example` kannte die Variable gar nicht. ADR-0077
  hatte als Betreiber-Handgriff nur „Key in `<stack-dir>/.env` legen" dokumentiert — aber
  `--env-file .env` setzt Variablen **ausschließlich für die Interpolation in der Compose-Datei**;
  kein Service hat `env_file:`, und die `.env` wird nirgends ins Image gemountet. `Settings.
  crypto_key` sah den Wert deshalb selbst dann nicht, wenn er korrekt in der `.env` stand.
  **Derselbe Riss traf drei weitere Stellen:** der `worker` hatte keinerlei SMTP-Konfiguration
  (der Wochen-Digest-Cron läuft dort, `smtp_host` fiel auf den Default `"localhost"` zurück),
  keine GitHub-Variablen (der Issue-Tracker wird in `worker.py` komponiert, nicht in der API),
  und `ops_readonly`/`ops_actions` fehlten sowohl in `init.prod.sh` als auch im Compose —
  die Betreiber-Grenze aus ADR-0071 galt auf Prod nur app-seitig.
- **Fix:** Alle betroffenen Variablen in die `environment:`-Blöcke von `api`/`worker`/`scheduler`
  (je nachdem, wer sie liest) + `.env.prod.example` + fester Dev-Key im Dev-Compose (sonst
  ist der Radicale-Pfad lokal nicht testbar). Ops-Rollen in `init.prod.sh` nachgezogen, mit
  Abbruch-Guard bei leerem Passwort; die Ops-URLs nutzen `${VAR:+…}`, damit ein bestehender Stack
  ohne gesetztes Passwort auf den dokumentierten `custode_app`-Fallback läuft statt auf eine
  kaputte URL — der Auto-Deploy wird nicht blockiert.
- **Regressionstest:** `backend/tests/test_compose_env.py` — reiner YAML-Test ohne Docker, im
  selben CI-Gate wie ruff/mypy. Prüft (1) je Service eine explizite Soll-Liste, (2) dass jeder
  `CUSTODE_*`-Key auf ein echtes `Settings`-Feld zeigt (ein Tippfehler ist genauso still wie ein
  fehlender Eintrag), (3) dass Integrations-Schalter in Dev **und** Prod gesetzt sind, (4) dass
  `.env.prod.example` jede interpolierte Variable dokumentiert. Negativprobe gefahren:
  Entfernen des Crypto-Blocks im Worker macht 3 Tests rot.
- **Lehre:** Die Lehre vom 2026-06-17 („Jede neue Settings-Abhängigkeit MUSS in ALLE
  Compose-Dateien") war richtig, aber **nur als Prosa** notiert — und hat sich deshalb wiederholt.
  Wiederkehrende Lehren gehören in ein Gate, nicht in eine Doku-Zeile (Prinzip E10). Zweitens:
  „Secret in die `.env` legen" ist als Betreiber-Handgriff **unvollständig**, solange nicht
  danebensteht, welcher Service ihn im `environment:` braucht — ein ADR-Handgriff muss den Weg
  bis in den Prozess beschreiben, nicht bis zur Datei. Drittens: Jobs im Worker (Cron, Outbox)
  haben eigene Adapter-Bedürfnisse — „die API hat es ja" ist kein Argument.

## 2026-07-19 — Einkaufsliste zeigte NIE Listen/Posten: Dexie-orderBy auf nicht-indiziertem Key  (Modul: shopping/web, Schwere: hoch)
- **Symptom:** `/shopping` zeigt dauerhaft „Diese Liste ist leer." und keinen Listen-Switcher —
  obwohl Dexie (IndexedDB) die Liste + Posten nachweislich enthält (Sync-Pull funktioniert).
  Kein Konsolen-Fehler, kein Error-State: die UI sieht schlicht `lists.data === undefined`.
  Gefunden bei den PWA-Manifest-Screenshots: erstmals wurde ein Haushalt MIT Daten headless
  durchgeklickt; alle bisherigen QA-Läufe nutzten den leeren QA-Haushalt (Empty-State sah „ok" aus).
- **Ursache:** `useShoppingLists` rief `db.lists.orderBy("name")` auf — die `lists`-Tabelle
  indiziert aber nur den Primärschlüssel (`"id"`, Schema v1). Dexie wirft dann `SchemaError:
  KeyPath name … is not indexed`; React Query schluckt den Fehler (retry, dann stiller
  error-State), `data` bleibt `undefined`, und die Seite rendert den Add-Pfad mit leerem
  Empty-State (der Create-Zweig prüft `data.length === 0`, der bei `undefined` nie greift).
- **Fix:** JS-Sortierung statt Index-orderBy (`(await db.lists.toArray()).sort(localeCompare)`)
  — eine Handvoll Listen braucht keinen Index. Übrige orderBy-Aufrufe geprüft: catalog(`count`),
  basics(`label`), outbox(`created_at`) sind indiziert.
- **Regressionstest:** `web/src/test/shopping-queries.test.ts` — treibt die ECHTEN Hooks gegen
  das echte Dexie-Schema (fake-indexeddb): wirft die queryFn, wird `isSuccess` nie wahr.
- **Lehre:** (1) Dexie-Queries gehören mit dem echten Schema getestet — Hook-Mocks (today.test)
  und Engine-Tests (sync) decken die Query-Schicht nicht. (2) Ein leerer QA-Haushalt „bestätigt"
  nur Empty-States: mindestens eine QA-Zelle muss MIT Daten laufen. (3) Stille React-Query-
  Error-States brauchen sichtbare Trio-Zustände — die Route zeigte „leer" statt „Fehler".

## 2026-07-08 — Frischer Login ohne Haushalts-Kontext: jede Modul-Query 403  (Modul: accounts/web, Schwere: hoch)
- **Symptom:** Nach Login auf einem neuen Gerät (frische Session, kein vorheriger Switch) liefert
  **jeder** haushalts-gebundene Endpunkt 403; `/today` zeigt vier „Etwas ist schiefgelaufen"-Kacheln,
  alle Modul-Screens wirken kaputt. Erst Konto→„Wechseln" heilt die Session. Gefunden durch die
  eingeloggte Prod-QA (Playwright-Matrix): die Desktop-Zelle loggte sich frisch ein → 105× 403,
  während die Mobile-Zelle (Session hatte den Haushalt erstellt) sauber war.
- **Ursache:** `POST /v1/auth/login` (und der Passkey-Login) mintete den Access-Token hart mit
  `household_id=None`; nur `refresh` (aus dem Redis-Gedächtnis der Login-Familie) und Child-Login
  scopten. Das Design nahm an, der Nutzer wählt danach aktiv — die UI erzwingt das aber nirgends,
  und Module feuern ihre Queries sofort.
- **Fix (#132):** Login/Passkey-Login lösen `resolve_sole_household` auf — genau eine (lebende)
  Mitgliedschaft → Token direkt darauf gescopt + als aktiver Haushalt der Familie gemerkt
  (Refresh trägt weiter); mehrere → weiterhin expliziter Picker. Web: `NoHouseholdState`-Fläche
  statt 403-Wand auf Modul-Routen ohne aktiven Haushalt.
- **Regressionstest:** `test_fresh_login_scopes_to_sole_household` (e2e inkl. Refresh-Persistenz),
  `test_fresh_login_multi_household_stays_unscoped`; vitest+axe für `NoHouseholdState`.
- **Lehre:** „Eingeloggt" ≠ „nutzbar" — jeder Auth-Pfad, der einen Kontext-Claim NICHT setzt,
  braucht einen erzwungenen UI-Pfad, der ihn setzt, sonst ist es ein Bug. Und: QA-Zellen müssen
  auch den **frischen** Login testen, nicht nur die Session, die die Daten angelegt hat.

## 2026-07-08 — Entferntes Mitglied konnte per Switch zurück in den Haushalt  (Modul: accounts, Schwere: hoch, Security)
- **Symptom:** Ein vom Admin entferntes Mitglied (Soft-Delete der Mitgliedschaft) sah den Haushalt
  weiterhin im Picker und konnte via `POST /v1/households/{id}/switch` wieder voll einsteigen.
  *(Korrektur 2026-07-31: der Nachsatz „bis der Retention-Reaper die Zeile nach 30 Tagen hart
  löscht" stimmte nie — `memberships` steht nicht in `_RETENTION_TABLES` und wird nie hart
  gelöscht. Der Zustand wäre also dauerhaft gewesen, nicht temporär. Am Fix ändert das nichts, an
  der Schwere schon.)*
- **Ursache:** Die Cross-Haushalt-Lookups `get_active_role` und `list_user_households` (maint-Rolle,
  kein RLS) filterten `Membership.deleted_at` nicht. Soft-Delete-Sichtbarkeit ist App-Sache — und
  genau diese zwei Autorisierungs-Reads hatten den Filter nicht.
- **Fix (#132):** Beide Queries filtern `deleted_at IS NULL`; eine soft-gelöschte Mitgliedschaft
  ist autorisierungstot.
- **Regressionstest:** `test_removed_member_cannot_switch_back` (Picker leer + Switch → 403,
  kein Auto-Scope beim Login).
- **Lehre:** Bei Soft-Delete ist **jeder** Autorisierungs-Read ein Pflicht-Filter-Kandidat —
  besonders maint-Pfade, die RLS bewusst umgehen. Checklisten-Punkt für neue maint-Queries:
  „filtert sie `deleted_at`?"

## 2026-07-04 — i18n: `{platzhalter}` erscheinen wörtlich im Production-Build  (Modul: web/i18n, Schwere: hoch)
- **Symptom:** Im Production-Build (nicht im Dev/Test) rendern **alle interpolierten Strings mit
  literalen Platzhaltern**: Theme-Toggle `aria-label` = „Design: {mode}" statt „Design: System",
  Impressum „{brand}" statt „Custode", und (potenziell) jede ICU-Plural-/Zähler-Anzeige als
  „{count, plural, …}". In jsdom/Dev funktionierte alles — der Bug war dadurch verdeckt und lief live.
- **Ursache:** Die i18n-Kataloge werden als **rohe Strings** geladen (`i18n.load({ de, en })`,
  `Record<string,string>`). Lingui interpoliert im **Production-Build nur COMPILIERTE** Nachrichten;
  rohe String-Nachrichten werden minifiziert nicht mehr zur Laufzeit kompiliert und daher unverändert
  (mit `{…}`) ausgegeben. Im Dev/Test kompiliert Lingui on-the-fly → grün, obwohl prod kaputt.
- **Fix:** In `web/src/i18n/core.ts` (bis 2026-08-01 `index.ts`, dann bei der
  Katalog-Trennung dorthin gewandert) jeden Katalog-Eintrag beim Laden über
  `compileMessage` (`@lingui/message-utils`, jetzt explizit als Dependency deklariert) in Linguis
  **Token-Form** übersetzen, bevor `i18n.load`. Interpolation + ICU-Plural verhalten sich damit in Dev
  und Prod identisch. (+6,8 kB gz im Vendor-Chunk, im Bundle-Budget.) (Slice 5g)
- **Regressionstest:** `web/src/test/i18n-compiled.test.ts` — prüft, dass die **aktive Katalog-Form
  kompiliert** ist (`typeof i18n.messages["theme.toggle"] !== "string"`; rohe Strings würden hier
  `"string"` liefern → rot) + dass Interpolation/Plural auflösen. Ein reiner Render-Test würde den
  Regress NICHT fangen (Dev-Modus maskiert ihn).
- **Lehre:** „Läuft in Dev/jsdom" ≠ „läuft in Prod" — gerade bei i18n. **Runtime-Kataloge müssen
  kompiliert werden**, sonst ist Interpolation ein reiner Dev-Effekt. Visuelle QA immer am
  **Production-Build** (`vite build` + `vite preview`), nicht nur im Dev-Server. Der frühere Merksatz
  „ICU-Plural geht runtime" galt nur für Dev.

---

## 2026-06-20 — Seed-Migration 0017: asyncpg-Array-Param braucht Liste, nicht String  (Modul: nutrition, Schwere: niedrig)
- **Symptom:** backend-CI rot (lokal grün/skip — kein Docker). `INSERT INTO ingredients … CAST(:aliases
  AS varchar[])` → `asyncpg.exceptions.DataError: invalid input for query argument $6: '{}' (a sized
  iterable container expected (got type 'str'))`.
- **Ursache:** Die Migration läuft im Test über den **asyncpg**-Treiber. Für einen Array-Parameter
  erwartet asyncpg eine **Python-Liste**, nicht das Postgres-Array-Literal als String (`'{}'`). Der
  Seed übergab Strings.
- **Fix:** `_SEED`-Aliases von String-Literalen (`'{}'`, `'{"Knoblauch"}'`) auf echte Listen (`[]`,
  `["Knoblauch"]`) umgestellt; `CAST(:aliases AS varchar[])` bleibt (gibt asyncpg den Element-Typ für
  leere Listen). `grams_per_unit` bleibt JSON-String + `CAST AS jsonb` (asyncpg akzeptiert das). (PR #26)
- **Regressionstest:** `test_recipes_http.py::test_ingredients_search` (Testcontainers) lädt die ganze
  Migration inkl. Seed → war rot, jetzt grün; läuft in CI bei jedem Container-Test.
- **Lehre:** In Alembic-Migrationen über asyncpg Array-Werte als **Python-Liste** binden (nie als
  PG-Array-Literal-String). Verstärkt „Docker-Integrationstests fängt nur CI": Migrationen lokal nicht
  ausführbar → immer CI-grün abwarten.

---

## 2026-06-15 — HEAD /healthz → 500 über den Reverse-Proxy  (Modul: kernel/telemetry, Schwere: mittel)
- **Symptom:** `GET /healthz` → 200 `{"status":"ok"}`, aber `HEAD /healthz` → 500
  (lokal wie über den Reverse-Proxy/Tunnel). Uptime-/Edge-Probes nutzen oft HEAD.
- **Ursache:** Nicht im eigenen Code. `opentelemetry-instrumentation-fastapi`
  scheitert in `_get_route_details` mit `AttributeError: '_IncludedRouter' object
  has no attribute 'path'`, wenn die getroffene Route über `include_router`
  eingebunden ist und per HEAD aufgerufen wird → die ASGI-Middleware wirft 500.
- **Fix:** `FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")`
  in `app/telemetry.py` — Health/Metrics werden nicht getract (ohnehin Probe-Noise),
  damit umgeht der Health-Pfad den Instrumentations-Bug.
- **Regressionstest:** `tests/test_health.py::test_healthz_head_not_500`
  (HEAD /healthz → 200; ohne den Fix 500).
- **Lehre:** Health-/Metrics-Endpoints grundsätzlich aus dem Tracing ausschließen
  (Noise + Probe-Methoden wie HEAD). Bei einem 500 erst den Traceback lesen, bevor
  man den eigenen Handler verdächtigt — hier lag es in einer Drittbibliothek.

## 2026-06-17 — Login/Register auf Prod → invalid_credentials trotz korrekter Daten  (Modul: infra/accounts, Schwere: hoch)
- **Symptom:** Auf Prod: `POST /v1/auth/register` legt den User an, antwortet aber
  `401 invalid_credentials` (CUS-D124-01) ohne Session-Cookies; `POST /v1/auth/login` mit
  denselben Daten ebenso `401`. In CI (Testcontainers) grün. Frontend zeigte „Etwas ist
  schiefgelaufen" (generischer Fallback für den unerwarteten Slug).
- **Ursache:** `docker-compose.prod.yml` (und `.dev.yml`) setzten **`CUSTODE_DATABASE_URL_MAINT`
  nicht**. `get_maint_sessionmaker()` fällt dann auf `database_url` (= `custode_app`) zurück. Die
  haushaltsübergreifenden Bootstrap-Pfade (`login`/`refresh`/Passkey-/Recovery-Lookup) laufen über
  `maint_session()` **ohne** gesetzten `app.user_id`-Scope → die `users`-RLS-Policy liefert für
  `custode_app` **0 Zeilen** → User „nicht gefunden" → `invalid_credentials`. Registrierung legt den
  User trotzdem an (self-scoped `custode_app`-Pfad mit Scope), nur die Auto-Login-Stufe scheitert.
  CI war grün, weil die Test-Fixtures `CUSTODE_DATABASE_URL_MAINT` explizit auf `custode_maint`
  setzen — der Compose-Pfad war nie getestet.
- **Fix:** `CUSTODE_DATABASE_URL_MAINT` (→ `custode_maint`) in **api + worker** beider Compose-Dateien
  gesetzt (prod: `${MAINT_DB_PASSWORD}`; dev: `custode_maint`). `custode_maint` hat die
  `maint_all`-Policies (USING true) → sieht cross-user. Branch `fix/maint-db-url-prod`.
- **Regressionstest:** Live-Smoke nach Deploy (register → 201 + Cookies, login → 200). Config-Lücke,
  CI-seitig schwer abbildbar; die HTTP-E2E-Tests prüfen den maint-Pfad bereits (mit gesetzter URL).
  **Follow-up:** Fail-loud-Guard beim Startup, wenn `env=production` und `database_url_maint` leer.
- **Lehre:** (1) **Jede neue Settings-/Rollen-Abhängigkeit MUSS in ALLE Compose-Dateien** (dev +
  prod), nicht nur in die Test-Fixtures — sonst grünes CI, rotes Prod. (2) Stiller Fallback
  (`url_maint or url`) verschleiert Fehlkonfiguration → besser fail-loud. (3) Bei „läuft in CI, nicht
  in Prod" zuerst den **Umgebungs-/Config-Diff** prüfen, nicht den Code.

## 2026-06-18 — SPA loggt nach 15 min aus (kein Token-Refresh im Client)  (Modul: web/auth, Schwere: hoch)
- **Symptom:** Nach ~15 min (Access-Token-TTL) landete der eingeloggte Nutzer beim nächsten
  Seitenaufruf/Navigieren auf `/login` — obwohl das rotierende Refresh-Cookie (30 Tage) gültig war.
- **Ursache:** Der generierte API-Client hatte nur einen Request-Interceptor (CSRF), aber **keinen
  Response-Interceptor**. Lief ein Request in ein `401` (abgelaufenes Access-Token), wurde nie
  `POST /v1/auth/refresh` versucht; `fetchMe` interpretierte zudem **jeden** Fehler als „nicht
  angemeldet" → Redirect auf `/login`. Die im Backend gebaute rotierende Refresh-Mechanik wurde
  clientseitig schlicht nicht genutzt.
- **Fix:** Response-Interceptor (`web/src/auth/client.ts`): bei `401` aus einer authentifizierten
  Route einmal `refresh` (single-flight, CSRF) und die Anfrage neu abspielen; Bootstrap-Routen
  (login/register/refresh/logout) ausgenommen (Loop-Schutz). `fetchMe` trennt `401` (→ `null`/unauth)
  von transienten Fehlern (→ throw → Error-State). Defensiv: jeder Fehlerpfad fällt aufs Original-`401`
  zurück, kann also nie schlimmer als vorher sein.
- **Regressionstest:** `web/src/test/auth-client.test.ts` (`handleResponse`: non-401 durchreichen;
  Bootstrap-401 ohne Refresh; authed-401 → Refresh+Replay; Refresh-Fehlschlag → Original-401).
- **Lehre:** Wer eine rotierende Session-Mechanik baut, muss den **Client-Pfad** mitdenken — sonst ist
  die Backend-Rotation totes Kapital und die Session endet still nach der Access-TTL. POST-Replays sind
  durch verbrauchte Request-Bodies begrenzt; der GET-`/me`-Pfad deckt den eigentlichen Logout-Fall ab.

## 2026-06-18 — Theft-Detection killt das lebende Opfer-Access-Token nicht  (Modul: accounts/auth, Schwere: mittel)
- **Symptom:** Bei `token_reuse` (gestohlenes Refresh-Token wird abgespielt) wurde die Redis-Access-
  Familie nur geburnt, wenn der **Anfragende** ein gültiges Access-Cookie mitschickte. Im realen
  Theft-Fall hat der Angreifer aber nur das Refresh-Token → `old_claims is None` → der Burn blieb aus.
  Folge: Die DB-Familie war zwar widerrufen (keine neuen Tokens mintbar), aber das **aktuelle, noch
  lebende** Access-Token des Opfers blieb bis zu 15 min (Access-TTL) gültig — der „sofortige Kill" der
  Theft-Detection war faktisch um die TTL verzögert.
- **Ursache:** Der Router burnte die Access-Familie über `old_claims.family_id`, das aus dem **Cookie
  des Aufrufers** stammt — eine Information, die der Angreifer typischerweise gar nicht besitzt. Die
  `family_id` des missbrauchten Tokens (dem Service über die DB-Zeile bekannt) wurde nicht durchgereicht.
- **Fix:** `service.refresh` wirft bei Reuse `TokenReuseError(family_id=sess.family_id)`; der Router
  burnt `revoke_access_family(exc.family_id)` — keyed am Token, nicht am Cookie. `family_id` bewusst
  NICHT im problem-`extra` (kein Leak in den Body).
- **Regressionstest:** `test_auth_http.py::test_reuse_burns_victims_live_access_without_requester_cookie`
  (Opfer rotiert einmal → hält ein frisches Access-Token; Angreifer spielt das verbrauchte Refresh-Token
  OHNE Access-Cookie ab → danach ist das Opfer-Access-Token in Redis tot). Ohne Fix rot.
- **Lehre:** Sicherheits-Revocations am **Identitäts-Objekt** (hier: Token-Familie aus der DB) verankern,
  nie an dem, was der (potenziell bösartige) Aufrufer freiwillig mitschickt. Out-of-band durchreichen,
  nicht über response-sichtbare Felder.

## 2026-06-19 — Kind anlegen → ForeignKeyViolation (Membership vor User geflusht)  (Modul: accounts, Schwere: mittel)
- **Symptom:** `POST /v1/household/children` → 500; CI-Backend rot mit
  `asyncpg.ForeignKeyViolationError: memberships_user_id_fkey … Key is not present in table users`.
  Lokal nicht reproduzierbar (Testcontainers-Tests skippen ohne Docker → erst CI fing es).
- **Ursache:** `create_child` fügt in EINER `scoped_session` den Kind-`User`, die `Membership`
  (FK `user_id → users.id`) und die `Consent`-Zeile per `session.add(...)` + EINEM `flush()` ein. Der
  Membership-INSERT lief vor dem User-INSERT (die Reihenfolge eines kombinierten Flushs ist hier nicht
  verlässlich „Parent zuerst"), also zeigte der FK ins Leere. PG-FK-Checks umgehen RLS — es war reine
  Insert-Reihenfolge, kein Sichtbarkeitsproblem.
- **Fix:** den Kind-`User` **vor** Membership/Consent flushen (`session.add(User)` → `await
  session.flush()` → dann Membership/Consent), so existiert die Zeile beim FK-Check. Branch
  `feat/s12-child-accounts`.
- **Regressionstest:** `test_auth_http.py::test_child_create_and_login` (+ übrige S12-Kind-Tests) —
  vor dem Fix CI-rot (FK-Violation), danach grün.
- **Lehre:** Beim Insert von **Parent + Child mit roher FK-ID** (kein ORM-`relationship`) nicht auf die
  Flush-Reihenfolge eines kombinierten `add()`-Batches verlassen — den Parent **explizit zuerst
  flushen**. Und: Testcontainers-only-Tests fangen nur in CI; mehrteilige DB-Inserts vor dem Merge
  bewusst gegen die CI-DB prüfen, nicht nur lokal skippen lassen.
