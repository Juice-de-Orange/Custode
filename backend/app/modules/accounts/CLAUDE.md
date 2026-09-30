# CLAUDE.md — Modul `accounts`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Identität, Mitgliedschaft, Rollen, Einladungen, Einstellungen (KONZEPT §5.1).

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul.
- `users` ist **global** (keine `household_id`); `households`/`memberships`/`invites`
  sind haushaltsgebunden.
- Pre-Tenant-Operationen (Registrierung/Login) laufen über den Auth-Bootstrap-Pfad,
  nicht über die haushalts-gescopte Session.

## RLS (Migration 0002)
- `households`: `id = app.household_id`
- `memberships` / `invites`: `household_id = app.household_id`
- `users`: `id = app.user_id` ODER Mitbewohner des aktiven Haushalts;
  WITH CHECK = nur eigene Zeile.
- Negativtest pro haushaltsgebundener Tabelle (User A ↛ Haushalt B → 0 Zeilen).

## Invarianten
- **Admin-Kontinuität:** Es existiert immer ≥ 1 `admin` pro Haushalt. Der letzte
  Admin kann nicht herabgestuft/entfernt werden (`would_leave_no_admin`).
- Eindeutige `(household_id, user_id)` je Mitgliedschaft.

## Schnittstellen (HTTP, Phase 1)
- `/v1/auth`: register (Auto-Login) · login (optionaler `totp_code`) · refresh (CSRF) ·
  logout (CSRF-frei, idempotent 204) · me · totp/setup|enable|disable|recovery-codes
  (2FA + Recovery-Codes, ADR-0022); login akzeptiert `totp_code` ODER `recovery_code`.
- `/v1/auth/passkeys`: register/begin|complete (eingeloggt) · login/begin|complete
  (passwortlos) · GET/DELETE (verwalten). WebAuthn via py-webauthn, rp_id aus dem Request
  abgeleitet, Challenge in Redis (ADR-0023).
- `/v1` Haushalte: households (anlegen/listen/switch/join) · household/invites (admin) ·
  household/members (Liste) · members/{id} PATCH Rollenwechsel + DELETE entfernen (admin) ·
  `GET/PATCH /v1/household/digest` (admin, CSRF) — Wochen-Digest pro Haushalt an-/abschalten
  (`settings_json['digest_enabled']`, Default an; P8-S7b).
- Sessions: opaque Access-Token in Redis + rotierender Refresh; httpOnly/Secure/
  SameSite=Lax-Cookies + Double-Submit-CSRF; Principal→RLS via Dependency. Design: ADR-0021.
- Cross-Haushalt-**Lesepfade** (Invite-per-Code, Haushalte listen, Mitgliedschaft vor
  Switch) laufen als `custode_maint` (read-only, Migration 0007); Schreibvorgänge als
  `custode_app`, gescopt auf den serverseitig abgeleiteten Ziel-Haushalt.
- **`api.py`-Export `list_digest_recipients`** (P8-S7): liefert je Haushalt die erwachsenen
  Mitglieder (`admin`/`member`) mit E-Mail für den Wochen-Digest. Läuft unter `custode_maint`
  (maint_all, 0006/0007); Kinder/Gäste ausgeschlossen. Reine Lese-Naht, kein Schreibpfad.

## Austritt (KONZEPT §5.1)
- `remove_member` widerruft **alle Sitzungen** der Person und gibt die Session-Familien zurück;
  der Router verbrennt danach ihre Redis-Access-Tokens. Grund: `Principal` wird aus dem **opaken
  Access-Token** gebaut und je Anfrage **nicht** gegen die Datenbank geprüft — das Token trägt
  `household_id` und `role` in sich. Ohne Widerruf behielte ein entferntes Mitglied bis zu
  15 Minuten vollen Zugriff auf genau den Haushalt, aus dem es entfernt wurde.
- Der Widerruf trifft **alle** Sitzungen, auch die für andere Haushalte: das Access-Token ist
  haushaltsgebunden, ein selektiver Widerruf wäre ein zweiter, schwächerer Pfad daneben.
- **Reihenfolge:** die Redis-Tokens fallen **vor** dem Commit (die Session-Dependency committet
  beim Verlassen). Bewusst diese Richtung — bricht die Transaktion ab, ist jemand ausgeloggt, der
  Mitglied bleibt; andersherum bliebe Zugriff offen. Wir fehlen Richtung **weniger** Zugriff.
- Das Ereignis `member.left` trägt den Rest. Drei Handler hängen daran: `calendar` (Feed-Token,
  CalDAV-Abos), `wearables` (Art.-9-Daten) und der **Ökonomie-Ablauf** in `app/member_exit.py`
  (Composition Root, weil er vier Module in fester Reihenfolge berührt und kein Modul ein anderes
  importieren darf). **Noch offen:** Vault-Rotation — braucht laut `docs/MODULES/vault.md` eine
  asymmetrische Pro-Mitglied-Identität und damit einen eigenen ADR.

## Sitzungs-Widerruf (nach BUGLOG 2026-08-01 — **bitte lesen, bevor du daran anfasst**)
- `revoke_all_sessions` nimmt **keine Session entgegen** und öffnet eine eigene `maint_session()`.
  Der Grund ist kein Stil: `auth_sessions` trägt `FORCE ROW LEVEL SECURITY` mit dem Prädikat
  `user_id = current_setting('app.user_id')`. Bekam die Funktion die Session des Aufrufers, passte
  das Prädikat bei drei von vier Aufrufern **zufällig** (dort ist die betroffene Person die
  aufrufende) und traf beim vierten — Entfernen durch einen Admin — **null Zeilen**, still.
- **Jede Funktion, die auf fremde Zeilen wirkt, darf die Aufrufer-Session nicht benutzen.** Die
  Signatur muss das erzwingen, nicht ein Kommentar.
- Der Widerruf committet **vor** dem Aufrufer. Bricht der ab, ist jemand ausgeloggt, der Mitglied
  bleibt — wir fehlen Richtung weniger Zugriff.

## Der Scope einer Sitzung kommt aus der Datenbank, nicht aus Redis (11-S1g)
- **`refresh` mintet nie mit dem Merkzettel.** `active_household:<family>` sagt nur, welchen
  Haushalt die Person zuletzt *gewählt* hat — gesetzt hat sie ihn selbst, und der Eintrag hält so
  lange wie das Refresh-Token (30 Tage). `service.resolve_refresh_scope` fragt je Rotation
  `get_active_role`; die **Rolle aus dem Merkzettel wird verworfen**.
- **Es gibt genau eine Bedingung, und sie steht in `get_active_role`** (lebende Mitgliedschaft UND
  lebender Haushalt). Wer sie hier nachbaut statt aufruft, hat zwei Fassungen, die auseinanderlaufen.
- **Kein Auto-Scope beim Rotieren.** `resolve_sole_household` gehört zur *Anmeldung* (#132). Eine
  Rotation darf einen Scope bestätigen, keinen neuen vergeben — sonst käme er nach jedem Entzug im
  nächsten Takt zurück.
- **Der Merkzettel wird nur geräumt, wenn die Datenbank ausdrücklich abgelehnt hat**
  (`cached is not None and scope is None`). `get_active_household` ist fail-closed und liefert bei
  einem Redis-*Lesefehler* dasselbe `None` wie bei „kein Merkzettel" — ohne die erste Bedingung
  machte **ein** Aussetzer aus einer Störung von Sekunden einen dauerhaften Verlust des
  Haushalts-Kontexts. Wer hier vereinfacht, baut genau diesen Datenverlust wieder ein.
- **`change_role` entwertet Access-Tokens, nicht Sitzungen.** Die Person bleibt Mitglied; ihre
  Rechte ändern sich. `access.revoke_access_tokens` lässt den Merkzettel deshalb **stehen** —
  `revoke_access_family` löscht ihn mit und würfe die Person in die Haushaltsauswahl zurück. Wer
  die beiden verwechselt, baut aus einem Rollenwechsel eine halbe Abmeldung.
- **`live_session_families` nimmt keine Session entgegen** — gleicher Grund wie
  `revoke_all_sessions`: `auth_sessions` filtert per RLS auf `user_id = app.user_id`, auf der
  Session des handelnden Admins käme die Abfrage **leer** zurück und der Entzug wäre wirkungslos.

## `logout` beendet Sitzung **und** Tokens — eine Funktion, kein Zweigpaar (11-B3)
- Die beiden Wirkungen hingen bis 11-B3 an **zwei verschiedenen Cookies**: `custode_rt`
  (Pfad `/v1/auth`, 30 Tage) trieb den Postgres-Widerruf, `custode_at` (Pfad `/`, 15 min) die
  Redis-Entwertung. Fehlte eines, lief nur die halbe Abmeldung — **in beide Richtungen**:
  ohne Access-Cookie blieben `access_family:<fam>` und `active_household:<fam>` stehen; ohne
  Refresh-Cookie blieb `revoked_at` **NULL** und die Sitzung liess sich zurückholen. Der zweite
  ist der ernstere: die Abmeldung sah vollständig aus.
- **Die Familie ist die Klammer**, nicht das Cookie. `service.logout` leitet sie aus dem ab, was da
  ist — vorzugsweise per Nachschlag zum Refresh-Token (findet auch ein bereits rotiertes), sonst
  aus den Access-Claims — und wirkt dann **unbedingt** auf beide Speicher. `DELETE
  /v1/auth/sessions/{family_id}` macht daneben genau dasselbe; dort ist die Familie ein Parameter.
- **Reihenfolge: erst Postgres, dann Redis.** Der dauerhafte Widerruf landet zuerst; scheitert
  danach Redis, lebt höchstens ein Access-Token seine Restminuten und ist nicht erneuerbar.
  Andersherum wäre die Sitzung mit dem Refresh-Cookie zurückholbar — wir fehlen Richtung
  **weniger** Zugriff, wie beim Austritt.
- **Was bleibt und bewusst so ist:** kommt gar kein auflösbares Token an, kann der Server die
  Sitzung nicht identifizieren (beide Token sind opak). Dann werden nur die Cookies geleert. Der
  einzige Sonderfall daneben: ein *fehlerhafter* Redis-Eintrag — `load_access` liefert `None`,
  der Schlüssel existiert trotzdem — wird einzeln geräumt.
- Vier Tests, einer je Cookie-Kombination (`test_auth_http.py`). Vorher waren nur die beiden
  symmetrischen Fälle gedeckt: „beide da" und „gar keine".

## Admin-Kontinuität ist gesperrt, nicht nur geprüft
- `_locked_roster` liest die lebenden Mitgliedschaften mit `FOR UPDATE` und `ORDER BY id`. Alle
  drei Funktionen, die die Invariante prüfen (`change_role`, `remove_member`, `leave_household`),
  benutzen sie. Ohne die Sperre ließen zwei gleichzeitige Austritte unter READ COMMITTED einen
  Haushalt mit **null** Admins zurück, aus dem es keinen Weg heraus gibt (BUGLOG 2026-08-01).
- **Eine Invariante über mehrere Zeilen, die nur im Anwendungscode geprüft wird, ist keine.**

## Selbst-Austritt (Slice A)
- `POST /v1/household/leave` — **jede Rolle**, `CurrentPrincipal` statt `AdminPrincipal`. Der
  Austritt trifft immer nur die aufrufende Person; `DELETE …/members/{id}` für die eigene ID zu
  öffnen hieße, eine Admin-Route für einen Sonderfall aufzuweichen.
- **Ein Kind kann nicht selbst gehen** (`child_cannot_leave`, 409). Nicht aus Bevormundung: das
  Konto hat weder E-Mail noch Passwort, `child_login` verlangt eine **lebende** Mitgliedschaft und
  `accept_invite` eine Sitzung, die das Kind ohne Login nicht herstellen kann. Der Austritt wäre
  eine unwiderrufliche Selbst-Aussperrung samt Punktestand — hinter einem einzigen
  Bestätigungsdialog. Das Entfernen durch die Verwaltung bleibt der Weg (eigener Test beweist,
  dass er existiert). Das Web blendet den Knopf für Kinder aus; der Server ist die Grenze.
- **Drei weitere Abweisungen (409), alle nur relevant, wenn die Person Admin ist:** `last_admin`
  (behebbar per Rollenuebergabe), `only_children` (behebbar per **Aufloesung**, seit 11-S1e)
  und `sole_member` — Letzteres gibt es **nur hier**:
  allein in einem Haushalt verlässt man ihn nicht, man löst ihn auf. Die *Kontolöschung* lässt
  denselben Fall zu, weil es dort kein „stattdessen" gibt und Art. 17 ein Recht ist. Der
  Unterschied ist Absicht und durch einen eigenen Test festgehalten
  (`test_the_two_paths_disagree_about_the_solo_household`) — wer beide vereinheitlicht, sperrt
  entweder jemanden aus seinem Löschrecht aus oder lässt verwaiste Haushalte zurück.
- **`exit_blocker_reason` ist die eine Stelle**, die das entscheidet. Kontolöschung und Austritt
  fragen dasselbe; zwei Fassungen bekämen irgendwann unterschiedliche Rollen beigebracht.
- Ab der Abweisung ist es derselbe Ablauf wie beim Entfernen: Tombstone, **alle** Sitzungen
  widerrufen, `member.left` in derselben Transaktion, Redis-Tokens vor dem Commit.

## Haushalts-Auflösung (11-S1e, ADR-0085)
- `POST /v1/household/dissolve` (admin, CSRF, **abgetippter Haushaltsname** als Bestätigung).
- **Die Admin-Kontinuität wird hier freigegeben, nicht umgangen.** `dissolve_household` liest
  denselben mit `FOR UPDATE` gesperrten Bestand wie `leave_household`/`change_role`, ruft
  `would_leave_no_admin` aber bewusst **nicht** — die Auflösung ist die einzige Operation, die die
  Invariante legitim beendet. Die Freigabe gehört in dieselbe gesperrte Transaktion wie die
  Prüfung, die sie ersetzt.
- **Keine Blocker.** Symmetrisch welche einzubauen wäre ein Zirkel: das hier *ist* der Ausweg.
- **Kinder-Konten werden mit vorgemerkt** — unter der Identität des Kindes, damit die
  `user_visibility`-Policy (`id = app.user_id`) die Grenze zieht, nicht dieser Code.
- **`on_member_left` steigt bei aufgelöstem Haushalt aus.** Nicht wegen Idempotenz, sondern weil
  `FOR UPDATE SKIP LOCKED` zwei Workern erlaubt, `household.dissolved` und ein `member.left`
  gleichzeitig zu ziehen — dann wäre die Ökonomie-Reihenfolge wieder offen.
- **Vier Eintrittstüren** lesen jetzt `households.deleted_at`: `get_active_role` (Switch-Gate),
  `child_login`, `accept_invite`, `create_invite`. Die letzte ist über den Sitzungs-Widerruf
  gedeckt und bekommt den Guard trotzdem — eine Sperre, die an einem vorherigen Schritt hängt,
  ist keine.
- **Phase 2 (11-S1f, ADR-0086) ist gebaut:** das Ausräumen liegt am Composition Root
  (`app/household_purge.py`), nicht hier — es berührt 39 Tabellen aus allen Modulen und darf
  deshalb in keinem einzelnen wohnen. Was dieses Modul beisteuert: `households.deleted_at` als
  Fälligkeitsquelle und die (getombstoneten) `memberships` als Liste der Identitäten, unter denen
  der Purge laufen muss. **Wer hier eine mitglieds-gescopte Tabelle ergänzt, muss nichts tun** —
  der Purge wiederholt seinen Durchgang ohnehin je Mitglied, genau damit diese Kopplung entfällt.

## Kontolöschung (Art. 17, 11-S1c)
- `DELETE /v1/auth/account` (jede Rolle, CSRF) merkt das **eigene** Konto zur Löschung vor:
  `users.deleted_at` gesetzt, alle Sitzungen widerrufen. Endgültig entfernt wird nach der Karenz
  (`retention_days`) — die Frist schützt vor Fehlbedienung und vor einem übernommenen Konto.
- **`users.deleted_at` war bis dahin eine tote Spalte** — nichts las sie. Eine Markierung hätte
  exakt nichts bewirkt.
- **Es gibt fünf Türen, und jede muss zu sein:** Passwort-Login, Kind-PIN, Passkey,
  Refresh-Rotation, Passwort-Reset. Die Prüfung ist deshalb **eine** Funktion (`_reject_deleted`),
  nicht fünf Zeilen — wer eine sechste Tür baut, findet sie beim Lesen der Nachbarn. **Jeder neue
  Anmeldeweg MUSS sie aufrufen.**
- Der Guard steht bei Login und Kind-PIN **nach** dem Argon2-Verify: sonst antwortete ein
  gelöschtes Konto messbar schneller und wäre von außen unterscheidbar. Beim Passkey steht er
  **vor** der Signaturprüfung (dort ist die Reihenfolge egal, aber der Slug beweist im Test, dass
  er griff).
- Die Antwort ist immer `invalid_credentials` — ein eigener Slug verriete, dass es dieses Konto
  gab und dass es gelöscht wird.
- **Zwei Sackgassen, zwei Antworten:** `last_admin` (es gibt andere Erwachsene → Rolle übertragen,
  behebbar) und `only_children` (außer der Person leben nur Kinder im Haushalt — ein Kind kann die
  Verwaltung nicht übernehmen, der Haushalt muss aufgelöst werden). Sie pauschal gleich zu
  behandeln, sperrte die Person **für immer** aus ihrem Löschrecht.
- **Der Austritt aus allen Haushalten geschieht SOFORT**, nicht erst mit dem Purge: je Haushalt
  wird die Mitgliedschaft getombstonet und `member.left` emittiert, damit dieselben vier Handler
  laufen wie beim Entfernen durch einen Admin. Die erste Fassung tat das nicht — und damit blieb
  der **ICS-Feed-Token eines selbst gelöschten Kontos gültig**, die CalDAV-Abos synchronisierten
  weiter und Art.-9-Daten blieben liegen. Die Karenz schützt davor, dass jemand sein *Konto* aus
  Versehen wegwirft; sie ist kein Grund, dreißig Tage lang weiter Gesundheitsdaten abzuholen.
  Kehrseite, die gesagt gehört: der Antrag ist damit **nicht zurücknehmbar**.
- **Der Purge nach der Karenz ist gebaut** (11-S1d, Cron 03:30, `app/account_purge.py`): er löscht
  die personenbezogenen Zeilen und lässt die `users`-Zeile **anonymisiert** stehen — damit bleiben
  die 27 Verweise ohne Fremdschlüssel gültig, und die Pseudonymisierung der Beiträge (KONZEPT §5.1)
  ist damit ebenfalls eingelöst. Die Haushalts-Auflösung samt Purge steht seit 11-S1e/11-S1f
  (Cron 04:00, `app/household_purge.py`).
  **Offen aus §5.1 ist nur noch die Vault-Rotation** (braucht eine asymmetrische Pro-Mitglied-
  Identität und damit einen eigenen ADR).

## Events (live)
- **publiziert:** `member.joined` (Beitritt), `member.role_changed` (Rollenwechsel),
  `member.left` (Entfernen) — transactional outbox via `kernel/events/emit.py` (Event-Zeile
  in derselben Tx wie die Fachänderung); dispatcht vom Worker via `kernel/events/registry.py`.

## No-Gos
- Keine Saldo-/abgeleiteten Felder als editierbare Spalten.
- Keine PII in Logs; **nie Token/Passwörter/Klartext-Secrets loggen**.
- Nie Access-/Refresh-Token im Response-Body zurückgeben (nur als httpOnly-Cookie).
- Refresh nie ohne Cookie-Rotation beantworten (sonst False-Theft).
- TOTP-Secret nie loggen; nur bei `totp/setup` (Enrollment, eigenes Konto) im Body —
  sonst nie zurückgeben.
