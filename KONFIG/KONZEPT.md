# KONZEPT v1.0 — **Custode**

> Status: **v1.0 Final (10.06.2026)** — freigegebene Entwicklungsgrundlage nach
> zwei Audits und Best-Practice-Recherche. Änderungen ab jetzt ausschließlich
> über Konzept-PRs/ADRs (Prinzip E9).
> Name: **Custode** (§15).
> Dieses Dokument ist die verbindliche Grundlage für die Entwicklung („Concept First").
> Änderungen am Konzept werden hier eingepflegt, nicht im Code improvisiert.

---

## 0. Zweck & Leitplanken

Ein kommerzielles Programm für Haushaltsplanung und -verwaltung: WebApp zuerst, danach
Android-App, iOS optional später. Zielgruppe von Einzelhaushalt bis Familie/WG.
Quellcode offen (AGPL-3.0). Betrieb primär als gehosteter Dienst; Self-Hosting ist
möglich, aber kein unterstütztes Angebot.

Entwicklungsphilosophie (verbindlich):

1. Saubere Architektur: große Features als eigenständige, erweiterbare Module.
2. Doku für Menschen UND AI: jedes Modul hat ein eigenes `docs/MODULES/<name>.md`,
   Architektur-Entscheidungen als ADRs, Bug-Historie in `BUGLOG.md`.
3. Concept First: erst lückenloses Konzept, dann Entwicklung. Release 0.1 erst bei
   Fertigstellung + eigener Testphase; 0.2 nach Bug-Hunts/Refactors.
4. Qualität vor Geschwindigkeit. Zeitbudget ist explizit nachrangig.
5. Kein Feature wird „light" gebaut und später vervollständigt — jedes Modul wird
   vollständig nach diesem Konzept umgesetzt. Was nicht in 0.1 gehört, steht im
   Konzept als spätere Phase, nicht als abgespeckte Version.
6. Es gelten die sieben Qualitätsprinzipien aus dem persönlichen CLAUDE.md-Standard:
   Lesbarkeit, Modularität, Prüfbarkeit, Robustheit, Einfachheit, Explizitheit,
   Konsistenz.
7. **Graceful Enhancement:** Wearables, Wetter und KI sind strikt optionale
   Verfeinerungen. Jede Funktion besitzt einen vollwertigen, gleich gut
   gestalteten Basis-Pfad ohne diese Datenquellen — sie verbessern Ergebnisse,
   sind aber niemals Voraussetzung. (Technische Verankerung:
   ARCHITECTURE.md §8.3 Null-Adapter; UX-Verankerung: ENTWICKLUNGSKONZEPT P5.)

Bewusst verworfene Ideen (mit Begründung, damit sie nicht wiederkommen):

- **Zero-Knowledge-Speicherung**: war Marketing-Gedanke; kollidiert frontal mit
  serverseitiger Automatik („Daten sind Macht", Auto-Mealplanner, Scheduling,
  Push-Inhalte). Stattdessen: ernsthaftes Sicherheitskonzept (Abschnitt 8) mit
  clientseitiger Verschlüsselung NUR für den Vault.
- **Self-Hosting als unterstütztes Angebot**: bewusst gestrichen (Support-Aufwand).
- **Vorratsverwaltung/Inventar (Grocy-Stil)**: erzeugt hohe Pflege-Friktion, die
  die Nutzung senkt. Die Einkaufsliste ist ein editierbarer Vorschlag, kein Bestandssystem.
  Stattdessen: „Basics"-Liste (Abschnitt 5.5).
- **Echtzeit-Chat**: Messaging ist Inbox + Kommentare + „Briefe", kein Chat-System.
- **Task-Verifizierung (Foto/Bestätigung)**: bewusst weggelassen — nervt im Alltag.
  Eskalationsventil: Admin kann Punktebuchungen manuell korrigieren.

---

## 1. Vision

Eine App, die den gesamten organisatorischen Alltag eines Haushalts abdeckt und deren
Module sich gegenseitig schlauer machen: Rezepte füttern den Mealplanner, der
Mealplanner füttert die Einkaufsliste, Wetter und Wearable-Daten füttern die
Aufgabenplanung, die Aufgabenplanung füttert die Gamification-Ökonomie. Intuitiv in
der Bedienung, als Admin tief konfigurierbar — inklusive der Möglichkeit, ganze
Module pro Haushalt abzuschalten, damit es nie „zu viel" wird.

**Positionierung (ein Satz):** Das Betriebssystem für euren Haushalt — alles in einer
App, EU-gehostet, werbefrei, fair bepreist.

**Differenzierung gegenüber Bestehendem:** Einzeln existiert fast alles besser
(Mealie/Tandoor: Rezepte; Grocy: Haushalts-ERP; Flatastic/OurHome/Nipto:
Chores+Gamification; Family Daily/Family Tools: Familien-Orga, aber US-Cloud).
Das Alleinstellungsmerkmal ist die **tiefe Integration der Module + die
Gamification-Ökonomie mit Marketplace + EU/Privacy-Haltung**. Kein Wettbewerber
verbindet Wearable-Daten, Wetter und Haushaltslogik zu vorausschauender Planung.

---

## 2. Zielgruppe

| Segment | Bedürfnis | Relevante Module |
|---|---|---|
| Einzelhaushalt | Essensplanung, Einkauf, persönliche Aufgaben | Rezepte, Mealplan, Einkauf, Kalender |
| Paar/Familie | Verteilung, Fairness, gemeinsamer Überblick, Kinder einbinden | + Aufgaben, Gamification, Kinder-Accounts |
| WG | Fairness, Marketplace („kauf mir Staubsaugen ab"), geteilte Infos | + Marketplace, Vault, Anleitungen |

Konsequenz: Die App muss im Ein-Personen-Modus genauso rund wirken wie im
6-Personen-Haushalt. Gamification, Marketplace und Rollen blenden sich bei
Einzelnutzung automatisch aus (Feature-Flags pro Haushalt, Abschnitt 4).

---

## 3. Geschäftsmodell

*§3 Geschäftsmodell — nicht Teil der Veröffentlichung.*

---

## 4. Modulprinzip & Architektur-Regeln

Jedes Modul ist eigenständig und kommuniziert ausschließlich über definierte
Schnittstellen. Konkret:

1. **Code-Schnitt:** ein Python-Package pro Modul (`modules/<name>/`) mit eigenem
   Router, Service-Layer, Modellen, Tests und Doku. Kein Modul importiert Modelle
   eines anderen Moduls; Zugriff nur über Service-Interfaces.
2. **Keine modulübergreifenden DB-Joins.** Wenn Modul A Daten von Modul B braucht,
   ruft es dessen Service oder reagiert auf dessen Events.
3. **Domain-Events** über ein Outbox-Pattern (Tabelle `events` + Worker), z. B.:
   `task.completed`, `market.listing.sold`, `mealplan.updated`,
   `recipe.imported`, `member.joined`. Module abonnieren Events, statt sich
   gegenseitig zu kennen. Das ist der Mechanismus, der „tiefe Zusammenarbeit bei
   sauberer Trennung" technisch erzwingt.
4. **Feature-Flags pro Haushalt:** Der Admin kann Module an/abschalten
   (`households.settings_json.modules`). UI blendet abgeschaltete Module vollständig aus;
   Backend lehnt Aufrufe ab. So bleibt die App für Minimalisten schlank.
5. **OpenAPI als Vertrag:** Das FastAPI-Schema ist die einzige Quelle der Wahrheit
   für alle Clients (Web: generierte TS-Typen via openapi-ts; Android später:
   generierter Kotlin-Client).
6. **Sanftes Löschen überall:** Nutzer-Löschungen sind 30 Tage wiederherstellbar
   („Zuletzt gelöscht"-Ansicht je Modul, technisch auf Tombstone-Basis, §7.3) —
   danach endgültig per Retention-Job. Ausnahmen nur, wo Recht es verlangt.
   **Zwei Vorgänge sind ausdrücklich nicht wiederherstellbar** und dürfen es auch nicht
   vorgeben: die **Kontolöschung** (Art. 17 — sie tritt sofort aus allen Haushalten aus) und die
   **Haushalts-Auflösung** (§5.1 — sie entwertet Zugänge und lässt Punkte verfallen). Bei beiden
   ist die 30-Tage-Frist eine *Purge-Verzögerung*, kein Undo, und die Oberfläche sagt das.

---

## 5. Module im Detail

Jedes Modul: Zweck → Kernfunktionen → Schnittstellen (Events/Services) →
Datenobjekte. Detail-Datenmodell in Abschnitt 10.

### 5.1 Accounts & Haushalt

**Zweck:** Identität, Mitgliedschaft, Rollen, Einladungen, Einstellungen.

**Kernfunktionen**
- Registrierung mit E-Mail + Passwort (Argon2id), optional Passkeys; TOTP-2FA.
- Haushalt erstellen/beitreten via Einladungslink oder Code (zeitlich begrenzt).
- **Rollen:** `admin` (alles, inkl. Ökonomie-Korrekturen, Modul-Flags, Belohnungen),
  `member` (Standard), `child` (eingeschränkt, s. u.), `guest` (zeitlich begrenzt,
  konfigurierbarer Lesezugriff, z. B. Ferienwohnungs-Gast sieht Anleitungen).
- Ein User kann in mehreren Haushalten Mitglied sein (z. B. eigene Wohnung +
  Elternhaus); aktiver Haushalt per Umschalter.
- **Kinder-Accounts:** werden vom Admin angelegt, ohne eigene E-Mail; Login via
  Benutzername + PIN innerhalb des Haushalts-Kontexts. Unter 14 (AT-Einwilligungs-
  alter) gibt der Admin/Elternteil die Einwilligung explizit im Anlage-Flow ab
  (protokolliert). Kinder: keine Wearable-Anbindung, kein Vault-Zugriff
  (default, konfigurierbar), vereinfachte UI.
- Profil: Anzeigename, Avatar, Arbeitszeiten-Konfiguration (füttert Scheduling),
  Ernährungspräferenzen/Allergien (füttert Mealplanner), Benachrichtigungs-
  einstellungen pro Kanal.

**Onboarding-Flow (verbindliche Sequenz, setzt P7 um):**
1. Konto anlegen (E-Mail/Passkey) →
2. Haushalt benennen + **Preset wählen: Solo / Familie / WG** (setzt
   Modul-Flags und Defaults sinnvoll vor, jederzeit änderbar) →
3. Mitglieder einladen (überspringbar) →
4. Drei Rezepte (eigene URL importieren oder aus den Starter-Rezepten
   wählen) →
5. Wochenplan-Entwurf generieren →
6. Einkaufsliste daraus zeigen — fertig, Ziel < 10 Minuten.
Kinder-Accounts, Wearables, Vault & Co. erscheinen bewusst NICHT im
Onboarding, sondern kontextuell später (P4 Progressive Offenlegung).

**Austritt, Löschung & Admin-Kontinuität (verbindlich):**
- **Haushalts-Austritt:** offene eigene Marketplace-Listings werden
  zurückgezogen (Escrow zurück), danach verfallen Restpunkte
  (`ref_type=member_exit`, Senke in 5.9); zugewiesene offene Tasks fallen
  in den Rotations-Pool zurück; Beiträge (Rezepte, Kommentare, Briefe)
  bleiben dem Namen zugeordnet, solange das Konto existiert.
- **Konto-Löschung (DSGVO):** Beiträge werden pseudonymisiert
  („Ehemaliges Mitglied"), personenbezogene Daten nach Löschkonzept (§9).
- **Vault bei Austritt:** Zugriff entzogen + **Schlüssel-Rotation**: neuer
  Haushalts-Key; Einträge werden beim nächsten Vault-Öffnen durch ein
  berechtigtes Mitglied neu verschlüsselt (Lazy-Rotation, bis dahin
  Warnhinweis im Vault).
- **Admin-Kontinuität:** Es existiert immer ≥ 1 Admin. Der letzte Admin
  kann weder austreten noch sich herabstufen, ohne vorher den
  „Admin übertragen"-Flow zu durchlaufen.

**Haushalts-Auflösung (Art. 17, 11-S1e):** Ein Admin kann seinen Haushalt auflösen. Das ist die
Operation, die zwei Sackgassen öffnet: der Selbst-Austritt lehnt für Alleinstehende mit
`sole_member` ab, die Kontolöschung mit `only_children` — beide verweisen auf die Auflösung.

- **Sie ist nicht rückgängig zu machen.** Leitplanke 6 („30 Tage wiederherstellbar") gilt für
  gelöschte *Inhalte*, nicht hierfür: die Auflösung entwertet sofort den ICS-Feed-Token, löscht
  Art.-9-Wearable-Daten hart, lässt Punktestände verfallen und beendet jede Sitzung. Eine
  Wiederherstellung gäbe einen ausgehöhlten Haushalt zurück. Die 30 Tage sind eine
  **Purge-Verzögerung, kein Undo**, und die Oberfläche muss das so sagen.
- **Die Admin-Kontinuität wird hier ausdrücklich freigegeben.** „Es existiert immer ≥ 1 Admin" ist
  die Invariante jeder anderen Operation; die Auflösung ist die einzige, die sie legitim beendet.
- **Kinder-Konten enden mit dem Haushalt.** Sie haben kein Login außerhalb davon (kein Passwort,
  keine E-Mail; die Anmeldung verlangt eine lebende Mitgliedschaft). Bliebe das Konto stehen, wäre
  es unerreichbar und von keinem Löschjob erfassbar — es wird deshalb mit vorgemerkt und läuft
  durch dieselbe Karenz.
- Erwachsene behalten ihr Konto. Wer keinen weiteren Haushalt hat, landet in einem **benannten**
  Zustand „du gehörst keinem Haushalt an" mit den zwei Wegen heraus (anlegen, beitreten) — nicht
  in einer Fehlerseite.

**Events out:** `member.joined`, `member.left`, `member.role_changed`, `household.dissolved`.

### 5.2 Rezepte

**Zweck:** Rezeptdatenbank des Haushalts; Fundament für Mealplanner und Einkaufsliste.

**Kernfunktionen**
- Manuelles Anlegen mit strukturiertem Editor: Zutaten (Menge, Einheit, kanonische
  Zutat), Schritte, Portionen, Zeiten, Tags, Fotos, Quelle.
- **Import per Link:** Abruf der Seite → Parsing von schema.org/Recipe (JSON-LD,
  liefern praktisch alle Rezeptseiten) → Fallback `recipe-scrapers` → Fallback
  LLM-Extraktion (Abschnitt 5.17) → Review-Screen vor dem Speichern (Nutzer
  bestätigt/korrigiert, v. a. Zutaten-Mapping).
- Portionen-Skalierung; Dupliziere-und-variiere; Bewertungen/Notizen pro Mitglied;
  „zuletzt gekocht"-Historie (kommt vom Mealplanner-Event).
- **Kochmodus:** Bildschirm bleibt wach (Wake-Lock), ein Schritt im Fokus mit
  den zugehörigen Zutatenmengen direkt im Schritt, antippbare Schritt-Timer,
  große Touch-Ziele für fettige Finger. (Übernahme T1)
- **Rechtliche Leitplanke:** importierte Fremdrezepte bleiben strikt im Haushalt.
  Kein öffentliches Teilen, kein haushaltsübergreifender Austausch von Importen.
  (Eigenkreationen-Sharing ist denkbar, aber bewusst NICHT in diesem Konzept.)

**Events out:** `recipe.created`, `recipe.imported`, `recipe.updated`.
**Services in:** Nutrition-Pipeline (5.3) für Nährwerte je Rezept.

### 5.3 Nutrition-Pipeline (Querschnittsdienst)

**Zweck:** Aus Zutatenlisten echte Nährwerte machen. Größtes Einzel-Arbeitspaket des
Projekts — wird bewusst als eigener Dienst geschnitten, nicht in „Rezepte" versteckt.

**Aufbau**
- **Kanonische Zutaten-Entität** (`ingredients`): Name (mehrsprachig DE/EN),
  Kategorie, Standard-Einheit, Dichte/Stückgewichte für Einheiten-Umrechnung
  (1 Zwiebel ≈ 110 g; 1 EL Öl ≈ 12 g …).
- **Nährwert-Quellen:** USDA FoodData Central (public domain, stark bei Frischware,
  englisch) + Open Food Facts (ODbL, stark bei Produkten, DE-Namen vorhanden aber
  lückenhaft). Mapping-Tabelle kanonische Zutat → Quelle/ID, einmal kuratiert,
  danach gecacht. Der deutsche Bundeslebensmittelschlüssel ist lizenzpflichtig und
  wird NICHT verwendet.
- Start-Korpus: die ~500 häufigsten Zutaten werden initial kuratiert (einmaliger
  Fleißaufwand, danach Long-Tail on demand mit manuellem Override-UI).
- Output je Rezept: kcal, Protein, Fett, KH, Zucker, Ballaststoffe pro Portion +
  Konfidenz-Kennzeichnung („geschätzt" wenn Mappings fehlen).

**Service:** `nutrition.calculate(recipe_id)`; Cache invalidiert bei Rezept-Änderung.

### 5.4 Meal Planner

**Zweck:** Wochenplanung des Essens — manuell komfortabel, optional vollautomatisch
nach einstellbarer Philosophie.

**Kernfunktionen**
- Wochenansicht (Frühstück/Mittag/Abend/Snacks konfigurierbar), Drag & Drop aus der
  Rezeptdatenbank, freie Texteinträge („Reste", „auswärts").
- **Philosophie-Profile** für die Automatik: Muskelaufbau, Abnehmen, Ausgewogen,
  Budget, Schnell unter der Woche — jeweils als Parametersatz (kcal-/Protein-Ziele,
  max. Zubereitungszeit werktags, Fleisch-Frequenz, Wiederholungs-Sperre X Tage,
  Saisonalität/Hitze-Gewichtung via Wetter).
- **Slot-Regeln:** feste, vom Nutzer verstehbare Regeln je Wochentag/Mahlzeit
  („Freitag Abend = Pizza", „werktags Mittag ≤ 20 min") begrenzen die
  Automatik und machen sie vorhersagbar — die Brücke zwischen manuell und
  vollautomatisch. (Übernahme T2)
- **Automatik-Engine:** Constraint-basiertes Scoring über die Rezeptdatenbank
  (kein ML in V1): erfüllt Nährwertziele über die Woche kumuliert, respektiert
  Allergien/Präferenzen aller Mitglieder, bevorzugt Zutaten-Überschneidungen
  (weniger Einkauf/Verschwendung), erklärt jede Wahl („gewählt weil: 38 g Protein,
  < 30 min, 3 Zutaten mit Dienstag gemeinsam"). Jeder Vorschlag einzeln
  austauschbar („neu würfeln").
- Ziel-Ebene: **Haushaltsplan** ist der Standard; optional persönliche Nährwert-Ziele
  pro Mitglied mit Portions-Faktoren (offener Punkt 17.2 für die Detail-UX).
- Wearable-Kopplung: hohe Aktivität (Kalorienverbrauch ↑) → Automatik darf
  kcal-Budget der Folgetage anheben (rein additiv, niemals restriktiv; keine
  „Strafen" — Gesundheits-Disclaimer in den AGB/Onboarding, das Produkt gibt keine
  medizinische Beratung).

**Events out:** `mealplan.updated` (→ Einkaufsliste), `mealplan.cooked`
(→ Rezept-Historie).

### 5.5 Einkaufsliste

**Zweck:** Die eine Liste, die im Supermarkt einfach funktioniert.

**Kernfunktionen**
- Generierung aus dem Mealplan: Zutaten aggregiert über die Woche, Einheiten
  zusammengeführt (Nutrition-Pipeline-Umrechnung), nach Marktkategorien sortiert
  (Obst/Gemüse, Kühlregal …; Kategorien-Reihenfolge pro Haushalt anpassbar =
  „mein Supermarkt-Layout").
- **Liste = Vorschlag, kein Bestand:** generierte Posten lassen sich mit einem Tap
  streichen („hab ich schon"). Bewusst kein Inventar (s. Abschnitt 0).
- **Basics-Liste:** haushaltsdefinierte Standardartikel (Klopapier, Kaffee …) als
  Ein-Tap-Hinzufügen und als wiederkehrende Vorschläge.
- **Schnellkatalog:** visueller Kachel-Katalog aus Haushalts-Historie + Basics,
  Hinzufügen per 1 Tap, lernende Kategorie-Zuordnung, Kachel-/Listenansicht
  umschaltbar. Bewusst ohne Angebote/Prospekte — werbefrei bleibt werbefrei.
  (Übernahme T4)
- **Reservieren:** Posten lassen sich beim Parallel-Einkauf „beanspruchen",
  damit zu zweit nichts doppelt im Wagen landet. (Übernahme T5)
- **Kundenkarten-Wallet:** optionales Komfort-Feature, Phase nach 0.2.
  (Übernahme T4, Zusatz)
- Manuelle Posten, Mengen, Notizen, Zuordnung „wer kauft", mehrere Listen
  (Supermarkt/Drogerie/Baumarkt).
- **Kollaborativ live:** Häkchen erscheinen bei allen Mitgliedern in Echtzeit
  (SSE/WebSocket-Kanal pro Haushalt) — zwei Leute können parallel im selben Markt
  abarbeiten.
- **Offline (Pflicht in der Android-App):** Liste vollständig lokal, Änderungen
  werden gequeued und gesynct, sobald Netz da ist (Sync-Design Abschnitt 7.4).
  Web-PWA: Service-Worker-Cache, Lesen + Abhaken offline, Sync bei Reconnect.

**Events in:** `mealplan.updated` → Regenerations-Vorschlag (niemals stilles
Überschreiben manueller Änderungen: Diff-Ansicht „5 neue Posten aus dem Wochenplan").

### 5.6 Persönlicher Kalender

**Zweck:** Termine + persönliche Aufgaben eines Mitglieds, mit Auto-Einplanung.

**Kernfunktionen**
- Klassischer Kalender (Tag/Woche/Monat/Agenda), Termine mit RRULE-Wiederholungen,
  Erinnerungen über das Notification-Modul.
- Persönliche Tasks mit Fälligkeitsfenster statt Fixtermin („diese Woche
  irgendwann") — die Scheduling-Engine (5.8) schlägt konkrete Slots vor und trägt
  sie auf Wunsch ein („Einkaufen: Do 17:30, nach der Arbeit, kein Regen").
- Konfiguration: Arbeitszeiten, No-Go-Zeiten, bevorzugte Erledigungs-Fenster.
- Privat by default; einzelne Einträge können für den Haushalt sichtbar geschaltet
  werden (Freigabe-Level: busy-only / Titel / Details).

### 5.7 Haushaltskalender

**Zweck:** Der gemeinsame Überblick.

**Kernfunktionen**
- Gemeinsame Events (Geburtstage, Besuch, Müllabfuhr via RRULE/Import).
- **Layer-System, konfigurierbar pro Mitglied:** Mealplan-Layer (was wird gekocht),
  Aufgaben-Layer (wer macht heute was), Events-Layer, freigegebene persönliche
  Einträge. Jeder Layer einzeln ein-/ausblendbar — so wird es nie „zu viel".
- Schreibrechte rollenbasiert (Kinder: nur eigene Aufgaben sehen, keine Events
  anlegen — konfigurierbar).

### 5.8 Scheduling-Engine (Querschnittsdienst)

**Zweck:** Ein Dienst beantwortet überall dieselbe Frage: „Wann ergibt diese Aufgabe
für diese Person Sinn?" Genutzt von persönlichem Kalender und Haushaltsaufgaben.

**Funktionsweise (regelbasiert, erklärbar, kein ML in V1)**
- Input: Aufgaben-Metadaten (Dauer-Schätzung, Ort innen/außen, Fälligkeitsfenster,
  RRULE), Personen-Kontext (Arbeitszeiten, belegte Slots, No-Go-Zeiten),
  Umwelt-Kontext (Wetter-Forecast für Outdoor-Tasks), Körper-Kontext (Wearable:
  Readiness/Schlaf — schwere Tasks nicht auf Erschöpfungstage).
- Scoring je Kandidaten-Slot, Top-Vorschläge mit Begründung in Klartext.
  Vorschläge sind immer Vorschläge — Auto-Eintrag nur wenn vom Nutzer aktiviert
  (opt-in pro Aufgabentyp).
- **Fairness-Tracking** (Übernahme aus „Daily"): bei rotierenden Haushaltsaufgaben
  führt die Engine ein gleitendes Fairness-Konto (gewichtete erledigte Punkte je
  Mitglied) und gleicht die Rotation automatisch aus; sichtbar als
  Fairness-Übersicht („Verteilung letzte 30 Tage").
- **Raum-Verfall (optional pro Haushalt):** Räume tragen einen
  Verschmutzungs-Indikator, der sich seit der letzten Erledigung zugehöriger
  Tasks zeitbasiert füllt (`decay_days` pro Raum/Task). Die Engine priorisiert
  „dreckige" Räume; eine **Raum-Heatmap** zeigt den Zustand des Hauses auf
  einen Blick. (Übernahme T8)

### 5.9 Haushaltsaufgaben & Gamification

**Zweck:** Wiederkehrende und einmalige Haushalts-Tasks, verteilt über Mitglieder,
mit Punkte-Ökonomie.

**Kernfunktionen**
- **Task-Templates** (Definition: Titel, Beschreibung, Punktwert, Dauer-Schätzung,
  innen/außen, RRULE-Schedule, Pool der zuständigen Mitglieder, Rotations-Modus:
  fair-rotierend / fix zugewiesen / first-come) erzeugen **Task-Instanzen**
  (konkretes Datum, konkrete Person, Status).
- Punktwerte setzt der Admin je Template; die App liefert Default-Vorschläge nach
  Aufwandsklasse (S/M/L/XL → 5/10/20/40), damit die Ökonomie konsistent startet.
- **Erledigung per Selbstmeldung, ohne Verifizierung** (Designentscheidung).
  Eskalationsventil: Admin kann jede Punktebuchung mit Begründung stornieren/
  korrigieren — sichtbar im Ledger, kein stilles Editieren.
- **Sanfter Wert-Verfall statt Strafen (entschieden, 17.1):** Niemandem werden
  Punkte vom Saldo abgezogen. Stattdessen schmilzt der **Punktwert** einer
  überfälligen Aufgabe täglich leicht (Default −10 %/Tag, Untergrenze 50 %,
  pro Haushalt einstellbar/abschaltbar): Wer trödelt, verdient weniger — die
  Währung bleibt knapp und wertvoll, ohne dass die App jemanden bestraft oder
  mit der Nicht-Negativ-Regel kollidiert. Überfällige Instanzen bleiben
  sichtbar, erzeugen Reminder und fließen ins Fairness-Konto.
- Kinder-Modus: vereinfachte Task-Karten, große Abhaken-UI, eigene
  Belohnungs-Sicht.
- **Kinder-Wochenziele:** persönliches Punkte-Wochenziel je Kind mit
  Fortschrittsbalken in der Kinder-Ansicht, vom Admin gesetzt. (Übernahme T7)

**Punkte-Ökonomie (Design-Invarianten)**
- **Ledger statt Saldo-Feld:** jede Bewegung ist eine doppelte Buchung
  (`points_ledger`: Quelle → Ziel, Betrag, Referenz, Zeitstempel). Salden sind
  Summen, niemals editierbare Zahlen. Das macht die Ökonomie auditierbar und
  Bugs reparierbar.
- **Quellen (Schöpfung):** ausschließlich Task-Erledigung (System → Mitglied).
- **Senken (Vernichtung/Transfer):** Belohnungs-Einlösung (Mitglied → System),
  Austritts-Verfall (Restpunkte → System beim Haushalts-Austritt,
  `ref_type=member_exit`, Ablauf in 5.1), Marketplace-Transfer (Mitglied → Mitglied; netto neutral, aber der Verkäufer
  „verliert" — wirkt als Knappheits-Mechanik).
- **Danke-Punkte:** kleine Mitglied→Mitglied-Transfers mit Nachricht („Danke
  fürs Einspringen"), gedeckelt (Default 10 P/Woche je Mitglied) — sozialer
  Kitt ohne Ökonomie-Verzerrung. (Übernahme T7)
- **Wochen-Challenge (optional pro Haushalt):** separate Wochen-Wertung aus dem
  Ledger berechnet, Reset Sonntagabend, Gewinner-Anzeige + optionale
  Gewinner-Belohnung aus dem Katalog. Greift nie in die Dauer-Währung ein —
  Spannung obendrauf, keine zweite Ökonomie. Die Gewinner-Belohnung ist eine
  **Admin-Gewährung ohne Punktabzug** (Ledger `ref_type=challenge_prize`) —
  der Sieg kostet den Gewinner nichts. (Übernahme T7)
- **Belohnungskatalog:** vom Admin frei definierbare reale Belohnungen
  (Name, Beschreibung, Preis, optional Bild, optional Kontingent/Cooldown) —
  z. B. „Kinoabend aussuchen 50 P", „1× nicht Abwaschen 30 P". Einlösung erzeugt
  Notification an den Admin + Eintrag in dessen Bestätigungsliste (die Belohnung
  selbst passiert in der echten Welt; die App trackt nur Einlösung/Erfüllung).
- Keine negativen Salden, nirgends. Deckung wird vor jeder Buchung geprüft.
- Währungsname folgt dem Produktnamen (offener Punkt 17.6); intern neutral
  „Punkte".

**Events out:** `task.completed` (→ Ledger, Fairness, Notifications),
`reward.redeemed`.

### 5.10 Marketplace

**Zweck:** Zugewiesene Aufgaben handelbar machen — der soziale Kern der Gamification.

**Mechanik (präzise, weil hier die Bugs wohnen)**
1. Verkäufer wählt eine ihm zugewiesene, offene Task-Instanz und setzt einen Preis.
   Der Preis wird sofort aus seinem Saldo **reserviert** (Escrow) — verhindert
   negative Salden und Doppel-Listings.
2. Listing erscheint im Haushalts-Marketplace + als Notification an in Frage
   kommende Mitglieder.
3. **Auto-Accept:** jedes Mitglied pflegt Regeln „Task-Typ X bis Preis Y automatisch
   annehmen". Matcht ein Listing, wird sofort zugeschlagen; bei mehreren Treffern
   entscheidet das Fairness-Konto — wer zuletzt am wenigsten übernommen hat,
   erhält den Zuschlag. *(Audit-Änderung A-05 — bestätigt am 10.06.2026.)*
4. Ohne Auto-Accept: Mitglieder können aktiv annehmen; der ursprüngliche Käufer-
   Kandidat hat **Ablehnungsrecht nur außerhalb seiner Auto-Accept-Regeln**
   (= seine eigene Konfiguration bindet ihn).
5. Bei Annahme wechselt die Task-Zuweisung. **Auszahlung des Escrow an den Käufer
   erst bei Erledigung der Task** (Selbstmeldung). Wird die Task bis Fälligkeit +
   Karenz nicht erledigt, fällt sie an den Verkäufer zurück und der Escrow wird
   freigegeben (verhindert „Punkte kassieren, nie machen").
   **Erlös-Klarstellung (Audit A-04):** Der Käufer erhält bei Erledigung
   beides — die Basis-Punkte der Aufgabe (zum dann gültigen, ggf. verfallenen
   Wert) plus den Escrow-Preis. Der Wert-Verfall (5.9) läuft auch für
   gelistete und übernommene Aufgaben weiter; die Fälligkeit bleibt beim
   Verkauf unverändert.
6. Verkäufer kann ein unverkauftes Listing jederzeit zurückziehen (Escrow zurück).

**Konfiguration (Admin):** Marketplace an/aus, Min-/Max-Preis relativ zum
Task-Punktwert (z. B. 50–300 %), Karenzzeit. Kinder-Accounts: Marketplace
standardmäßig aus, vom Admin aktivierbar (Audit A-07).

**Events out:** `market.listing.created`, `market.listing.sold`,
`market.trade.settled`, `market.trade.reverted`.

### 5.11 Vault (geteilte Zugangsdaten)

**Zweck:** Kleiner, scharf begrenzter Bereich für geteilte Secrets des Haushalts
(Streaming-Login, Garagencode, WLAN-Gast). Ausdrücklich KEIN vollwertiger
Passwortmanager und wird auch nie einer.

**Sicherheits-Design (die eine Stelle mit clientseitiger Verschlüsselung)**
- Vault-Einträge werden **im Client ver- und entschlüsselt** (libsodium,
  XChaCha20-Poly1305). Der Server speichert nur Ciphertext. Begründung: bei einem
  Server-Breach dürfen ausgerechnet Passwörter nicht lesbar sein — das ist mit
  vertretbarem Aufwand machbar, weil der Vault klein und featurearm ist (keine
  Suche über Inhalte nötig, keine Server-Verarbeitung).
- Schlüsselmodell: ein **Haushalts-Vault-Key** (symmetrisch), verschlüsselt
  abgelegt pro Mitglied — eingepackt mit einem Key, der aus einer separaten
  **Vault-Passphrase** des Mitglieds abgeleitet wird (Argon2id). Beitritt neuer
  Mitglieder: ein bestehendes Mitglied mit Vault-Zugriff bestätigt und packt den
  Key für den Neuen ein (Public-Key-Umschlag, Schlüsselpaar wird beim Onboarding
  erzeugt). Der private Schlüssel jedes Mitglieds liegt serverseitig
  ausschließlich verschlüsselt — eingepackt mit einem Argon2id-Schlüssel aus
  der Vault-Passphrase (Bitwarden-Muster); der Recovery-Code umhüllt denselben
  privaten Schlüssel als zweiten, unabhängigen Weg.
- **Recovery:** pro Mitglied ein einmalig angezeigter Recovery-Code (druckbar).
  Ohne Passphrase + ohne Recovery-Code sind Vault-Daten weg — wird in der UI
  unmissverständlich kommuniziert. (Rest der App ist davon unberührt.)
- Zugriffssteuerung pro Eintrag/Gruppe (wer sieht was), Kinder default ohne
  Zugriff. Zugriffe werden im Audit-Log protokolliert (Metadaten, nie Inhalte).
- Clipboard-Hygiene: Auto-Clear-Hinweis, kein Inhalt in Notifications, niemals
  Inhalte in Logs/Fehlermeldungen.
- **Angriffsfläche Web (Audit A-06):** Der Browser ist der schwächste
  Vault-Client (XSS). Konsequenz: strikte CSP ohne Inline-Skripte, keine
  Dritt-Skripte auf Vault-Routen, Krypto ausschließlich via libsodium-wasm.

### 5.12 Messaging & Notifications

**Zweck:** Alles, was Mitglieder erreichen muss — ohne Chat-System zu sein.

**Drei Ebenen**
1. **System-Notifications:** generiert aus Events („Anna hat ‚Staubsaugen Mittwoch'
   von dir gekauft", „Wochenplan fertig", „Belohnung eingelöst"). Pro Nutzer
   konfigurierbar je Ereignistyp und Kanal: In-App-Inbox, Web Push (VAPID),
   später FCM (Android), E-Mail-Digest (täglich/wöchentlich).
2. **Kommentare an Objekten:** Threads an Rezepten, Tasks, Events, Listen,
   Anleitungen („nimm das Waschmittel aus dem Keller"). @-Mentions erzeugen
   Notifications.
3. **Briefe:** kleine asynchrone Nachrichten Mitglied → Mitglied(er), bewusst als
   „Brief" inszeniert (Betreff, Text, optional Anhang/Bild), landen in der Inbox
   mit Gelesen-Status. Kein Echtzeit-Chat, keine Tipp-Indikatoren — das ist ein
   Feature, kein Mangel (Ton des Produkts: ruhig statt pingend).

**Technik:** Inbox persistent in DB; Live-Zustellung über den bestehenden
SSE/WebSocket-Haushaltskanal; Push-Versand über Worker.
Die konkrete **Default-Matrix** (Ereignistyp × Kanal × Rolle) ist
Phase-1-Deliverable `docs/NOTIFICATIONS.md` und muss das P1-Budget
(max. 1 gebündelter Push/Tag + direkte persönliche Ereignisse) nachweisen.

**Feedback & Support (nutzerseitig):** In-App-Feedback auf jeder Sicht;
Meldungen wahlweise mit Diagnose-Anhang (Client-Log-Ringpuffer, App-Version,
letzte Fehler-Referenzcodes — strikt opt-in pro Meldung, niemals Inhalte).
Meldungen landen in der Beta als GitHub-Issues, später im Support-Postfach.
Dazu: „Was ist neu"-Ansicht (Release-Notes) und Platz für Betreiber-Banner
(Wartung/Ankündigung) — leise, P1-konform. Umsetzung (Phase 8): eigenes
Modul `feedback` (RLS-isolierter Kanal **an** den Betreiber — abzugrenzen von
`messaging`, das Mitglied↔Mitglied bleibt); der wöchentliche E-Mail-Überblick
ist das Logik-Modul `digest`.

**Betreiber-Konsole (`backoffice`, ab Phase 8, §14):** Der Betreiber bedient
Support und Betrieb über eine eigene Konsole (`/ops`, separate Subdomain), die
**ausschließlich Aggregat-Views liest, nie Fachzeilen** (Betreiber-Grenze, §6).
Eigene, nicht haushaltsgebundene Datenobjekte: `operators` (Betreiber-Konten,
Login mit Pflicht-2FA), append-only `audit_log` (jede Betreiber-Aktion
revisionssicher), `ops_banners` (die o. g. Banner) und `global_flags`
(systemweite Feature-Schalter). Details: ARCHITECTURE §8.6/§9.

### 5.13 Anleitungen (Wissensdatenbank)

**Zweck:** Dokumentation rund um Haus & Haushalt — schnell findbar.

**Kernfunktionen**
- Artikel mit Rich-Text/Markdown, Bildern und Datei-Anhängen (PDF, Fotos);
  Kategorien + Tags; Volltextsuche (Postgres FTS mit deutscher Konfiguration;
  Meilisearch erst falls FTS qualitativ nicht reicht).
- **Ansprechpartner-Einträge:** Kontakte (Heizungstechniker, Vermieter, Notdienste)
  als strukturierter Typ, verknüpfbar mit Artikeln („Wartung Therme" → Techniker).
- Zugriffsrechte pro Artikel/Kategorie (Rollen + einzelne Mitglieder + Gast-Flag —
  der Ferienwohnungs-Usecase: Gast-Account sieht genau die markierten Anleitungen).
- Versionierung leichtgewichtig (letzte N Versionen, Wiederherstellen).

### 5.14 Notizen (Übernahme aus „Daily")

**Zweck:** Der schnelle Zettel — fehlte im ursprünglichen Konzept, war aber
Kernbestandteil von „Daily" und schließt eine Alltagslücke (Gedanken, die noch
kein Task/Rezept/Artikel sind).

**Kernfunktionen:** persönliche + geteilte Notizen, Markdown, Pin/Archiv, Suche.
Eine Notiz kann auf das Haushalts-Dashboard gepinnt werden — die digitale
Pinnwand am Kühlschrank. (Übernahme T10)
Geteilte Notizen: LWW auf den Inhalt, die letzten 5 Versionen bleiben
wiederherstellbar, „zuletzt geändert von" ist sichtbar (Audit A-13).
Bewusst simpel — Notizen, die zu Struktur reifen, wandern per „Konvertieren zu…"
(Task / Einkaufslisten-Posten / Anleitung) in die passenden Module. Das ist die
saubere Antwort auf „zu simpel vs. zu komplex": die Notiz bleibt simpel, die
Struktur wohnt woanders.

### 5.15 Wearables

**Zweck:** Körperdaten nutzbar machen für Scheduling und Mealplanner.
**Strikt optional (Leitplanke 7):** Alle abhängigen Funktionen besitzen einen
gleichwertigen Basis-Pfad ohne Wearable-Daten; die Daten verfeinern nur.

**Anbindungs-Strategie (zweigleisig, gestaffelt)**
- **Pfad A — Health Connect (Android-App, ab Phase Android):** liest lokal vom
  Gerät; deckt mit EINER Integration Garmin, Oura, Samsung u. a. ab, ohne
  API-Anträge. Garmin liefert dorthin u. a. Schlaf, Herzfrequenz, Schritte,
  Kalorien, Gewicht (One-Way, ab Android 14, mit Nutzer-Consent). Die App selbst unterstützt
  Android 10+ (17.7); einzelne Health-Connect-Quellen setzen neuere
  Android-Versionen voraus — das macht das UI je Quelle transparent.
- **Pfad B — Cloud-APIs (funktioniert schon mit der reinen WebApp):**
  - **Oura:** OAuth2-App self-serve registrierbar; Personal Access Tokens sind
    seit Dez 2025 abgeschaltet, OAuth2 ist Pflicht. Liefert auch Readiness/
    Sleep-Score (gibt es in Health Connect nicht).
  - **Garmin Cloud (Health API):** erst in späterer Phase — erfordert
    Business-Approval mit Use-Case-/Firmen-Prüfung; einzelne Premium-Metriken
    ggf. lizenzpflichtig. Antrag stellen, sobald das Produkt live vorzeigbar ist.
- **Genutzte Datentypen:** Schlafdauer & -score, Readiness/Body Battery (nur
  Cloud-Pfade), Ruhepuls, Schritte, aktive Kalorien. Nur lesend, nur die Typen,
  denen der Nutzer einzeln zugestimmt hat.
- **Verwendung:** Scheduling-Score (5.8), kcal-Budget-Anpassung (5.4),
  Wochen-Insight („deine anstrengendste Woche seit …" — nice-to-have, spät).
- **Datenschutz:** Gesundheitsdaten = Art. 9 DSGVO → eigener, expliziter
  Consent-Flow pro Datentyp, getrennte Tabellen mit engem Zugriff, konfigurierbare
  Retention (Default 90 Tage Rohwerte, Aggregate länger), Lösch-Button der
  wirklich löscht. Kinder-Accounts: keine Wearables.

### 5.16 Wetter

**Zweck:** Umwelt-Kontext für Scheduling (Outdoor-Tasks nicht bei Regen) und
Mealplanner (Hitze → leichte/kalte Gerichte).

- Quelle: **Open-Meteo**. Free-Tier ist nur nicht-kommerziell → ab kommerziellem
  Betrieb kostenpflichtiger Plan (Standard 29 USD/Monat, 1 Mio Calls) ODER
  Self-Hosting der AGPL-Software (kommerziell erlaubt, Änderungen offenlegen).
  Entscheidung: **Abo**, Self-Hosting lohnt den Betriebsaufwand erst bei Skalierung.
- Caching pro Haushalts-Standort (eine Forecast-Abfrage deckt alle Mitglieder),
  Standort = grobe Koordinate, vom Admin gesetzt, nicht Geräte-GPS.
- Attribution „Weather data by Open-Meteo" im UI (CC-BY-4.0-Pflicht).

### 5.17 KI-Assistenz & Quick-Capture „Zuruf"

**Zweck:** Zwei Dinge in einem Modul: (a) der **Zuruf** — das universelle
Freitext-Eingangstor des Produkts („muss mir ein Deo für die Arbeit
besorgen"), (b) das gekapselte LLM als Werkzeug dahinter. Kein Chatbot.

**Zuruf — Eingang überall:** Auf Mobile ist der FAB immer der Zuruf. Im Web
öffnet `Strg/Cmd+K` die **Palette** — Suche und Zuruf als EIN Eingang statt
zweier konkurrierender Shortcuts: Tippen durchsucht live alles (Rezepte,
Aufgaben, Anleitungen, Notizen, Posten); ein Freitext ohne Treffer wird mit
Enter zum Zuruf, das Präfix `>` erzwingt ihn direkt. Später: Android-Widget
+ Share-Target. Eine Zeile, optional Hint-Tags, Enter, fertig — gedacht für
den Moment, in dem keine Zeit zum Planen ist.

**Pipeline (dreistufig):**
1. **Regel-Parser zuerst** (deterministisch, offline, ohne LLM — der
   P5-Basispfad): erkennt Kauf-Verben („besorgen/kaufen/holen" → Posten),
   Mengen, Datums-/Zeitangaben, `@Name`, `#tags`, bekannte Zutaten/Basics.
2. **LLM-Anreicherung** (lokal, Ollama): zerlegt die Absicht in
   Aktionsvorschläge nach striktem JSON-Schema (validiert — Freitext wird
   nie direkt ausgeführt) und ergänzt, was der Parser nicht sieht
   (z. B. „für die Arbeit" → Routine-Bezug, Folge-Task).
3. **Vorschlagskarte** (P3): erkannte Aktionen mit Klartext-Begründung,
   1 Tap bestätigen, ändern oder verwerfen. Opt-in-Einstellung pro
   Aktionstyp: „bei hoher Konfidenz still ausführen" — still Ausgeführtes
   erscheint im Aktivitäts-Feed mit Undo. Latenzbudget 2 s; dauert das LLM
   länger, läuft die Verarbeitung asynchron und die Karte landet in der Inbox.

**Aktionsketten (das eigentliche Konzept):** Ein Zuruf darf **mehrere
verknüpfte Artefakte mit Abhängigkeiten** erzeugen. Der Referenzfall:

> *„muss mir ein Deo für die Arbeit besorgen"* →
> ① Posten **„Deo"** auf der Drogerie-Liste (Quelle: zuruf) +
> ② persönlicher Task **„Deo in den Rucksack"** mit Aktivierung
> `on_item_checked(①)` und Scheduling-Hinweis `vor Routine „Arbeit"`.
> Beim Abhaken des Postens im Laden feuert `shopping.item.checked`,
> der Task wird scharf, die Scheduling-Engine terminiert die Erinnerung
> auf den Morgen des nächsten Arbeitstags (vor Abfahrt) — P1-konform als
> eine leise Notification. Persönliche Tasks bleiben punktelos (5.6/5.9).

**Routinen (neue Profil-Erweiterung, auch fürs Scheduling):** benannte,
wiederkehrende Kontexte je Mitglied — „Arbeit Mo–Fr, Abfahrt 7:45",
„Sport Di 18:00" — mit Vorlaufzeit. Zuruf-Tags wie `#arbeit` und Phrasen
wie „für die Arbeit" binden Aktionen daran; die Scheduling-Engine nutzt
Routinen als Anker für „die richtige Zeit".

**Hint-Tags (optional, erhöhen Treffsicherheit, nie Pflicht):**
`#liste` `#task` `#notiz` (Zieltyp erzwingen) · `@Name` (Zuweisung) ·
`#heute` `#morgen` `#sa` (Zeit) · `#arbeit` `#sport` (Routine) ·
`#haushalt` (Haushalts- statt persönlicher Task). Ohne Tags entscheiden
Parser + LLM; die Karte zeigt immer, was verstanden wurde.

**Ohne-LLM-Pfad (Leitplanke 7 / P5, vollwertig):** Der Regel-Parser deckt
die häufigen Muster ab; was er nicht sicher zuordnet, landet als
„Unsortiert"-Eintrag in der Inbox mit 1-Tap-Triage (→ Liste / Task /
Notiz). Der Zuruf funktioniert damit komplett ohne KI — nur weniger magisch.

**Weitere LLM-Einsätze (unverändert, eng begrenzt):** Rezept-Import-Fallback
mit Review-Screen (5.2), Formulierungshilfen für Anleitungen und Briefe.

**Betrieb & Grenzen:** LLM ausschließlich auf eigener EU-Infrastruktur
(Ollama) — Datenschutz-Argument; strikt als austauschbarer Adapter
(`LlmPort`); Feature-Flag pro Haushalt; Längen-/Kostenbudget pro Aufruf;
**Vault-Inhalte erreichen den LLM-Kontext nie** (N-3 in 5.19). Kein
KI-Feature ist für Kernfunktionen erforderlich.

**Events:** `capture.created`, `capture.processed` (→ Zielmodule, Feed).

### 5.18 Finanzen (eigenes Modul, Phase 13 — nach 0.1)

**Zweck:** Geteilte Ausgaben fair abrechnen — der WG-Anker, ohne den eine WG
zwingend eine zweite App installiert. (Übernahme T6)

**Kernfunktionen**
- Ausgaben erfassen: wer hat bezahlt, Betrag, Kategorie, Notiz, optional Beleg-
  Foto; wiederkehrende Ausgaben (Miete, Internet) per RRULE.
- Aufteilung pro Ausgabe: gleichmäßig, Prozent oder feste Anteile;
  Mitglieder-Teilmengen („nur wir drei waren essen").
- Salden-Übersicht „wer schuldet wem" + **Kassensturz**: Ausgleich mit
  minimaler Transfermenge, als Settlement protokolliert; CSV-Export.
- **Strikt getrennt von der Punkte-Ökonomie** — Geld ist Geld, Punkte sind
  Punkte; keine Umrechnung, nie. Keine Bank-Anbindung (bewusst: kein
  PSD2-/Compliance-Rattenschwanz), Währung zum Start EUR.

**Events out:** `expense.created`, `settlement.completed` (→ Notifications).

### 5.19 Synergie-Katalog (modulübergreifende Abläufe, verbindlich)

Kein eigenes Modul, sondern der vollständige Katalog der Querverbindungen —
das ist „Daten sind Macht" in konkret. Jede Zeile ist ein Event-/Service-Pfad
nach den Regeln aus §4 (kein Modul kennt ein anderes direkt). ✨ = optionales
Enhancement (Leitplanke 7: Basis-Pfad existiert immer ohne).

**Küche**

| ID | Synergie (Auslöser → Wirkung) | Module | Phase |
|---|---|---|---|
| S-01 | Event-Flags „auswärts / Gäste(n) / Abwesenheit" steuern die Mealplan-Automatik: Slot überspringen, Portionen +n, Resteverwertung | 5.7→5.4 | 6 |
| S-02 | Rezeptschritte mit Vorlauf (auftauen, marinieren, Teig) erzeugen beim Einplanen automatisch einen Vorbereitungs-Task am Vortag („Hähnchen auftauen") | 5.2/5.4→5.6 | 6 |
| S-03 | „Wer kocht heute": Mealplan-Slot ist mit Task-Template „Kochen" verknüpfbar — Rotation, Fairness und Punkte fürs Kochen, eigener Kalender-Layer | 5.4↔5.9/5.8 | 6 |
| S-04 | Kochmodus: fehlende Zutat antippen → sofort auf die Einkaufsliste | 5.2→5.5 | 3 |
| S-05 | ✨ Wiederkauf-Rhythmen: aus der Abhak-Historie lernt die Liste Intervalle der Basics („Kaffee ≈ alle 3 Wochen") — weiches Vorratsgefühl ohne Inventar-Pflege | 5.5 intern | 5 |
| S-06 | Abgeschlossener Einkauf → 1-Tap-Ausgabe in Finanzen (Zahler = Einkäufer, Split = Haushalt) | 5.5→5.18 | 13 |
| S-07 | ✨ Belohnungs-Typ „Wunschgericht": Einlösung reserviert einen Mealplan-Slot für das Wunschessen des Einlösers (Kinder-Liebling) | 5.9→5.4 | 6 |
| S-08 | ✨ Gäste-Präferenzen am Event („vegetarisch") fließen in die Automatik | 5.7→5.4 | 6 |

**Aufgaben & Ökonomie**

| ID | Synergie | Module | Phase |
|---|---|---|---|
| S-09 | Abwesenheits-Flag (Urlaub) pausiert die Rotation für Abwesende; das Fairness-Konto rechnet Abwesenheit heraus — sonst wird Fairness unfair | 5.7→5.8/5.9 | 5 |
| S-10 | ✨ Engpass-Erkennung: kollidiert eine zugewiesene Task mit dem Kalender, schlägt Custode proaktiv ein Marketplace-Listing vor („Mittwoch wird eng — verkaufen?") | 5.8→5.10 | 5 |
| S-11 | Task-Template verlinkt eine Anleitung; bei Erst-Erledigung wird sie eingeblendet („So entkalkt man die Maschine") | 5.9↔5.13 | 7 |
| S-12 | Wartungs-Tasks tragen Ansprechpartner (Therme → Techniker, 1-Tap anrufen) | 5.9↔5.13 | 7 |
| S-13 | Raum-Heatmap als Aktionsfläche: aus „rotem" Raum direkt die zugehörigen Tasks einplanen | 5.8/5.9 | 5 |
| S-14 | ✨ Wearable-Schonung: XL-Tasks meiden Erschöpfungstage — ausschließlich auf Basis der eigenen Daten, nur für eigene Vorschläge | 5.15→5.8 | 9/10 |

**Kalender & Umwelt**

| ID | Synergie | Module | Phase |
|---|---|---|---|
| S-15 | ✨ Regenrisiko-Hinweis an Outdoor-Events mit Verschiebe-Schnellaktion („Grillabend Sa: 80 % Regen") | 5.16→5.7 | 5 |
| S-16 | Externe CalDAV-Abos zählen im Scheduling als „belegt" — Vorschläge respektieren Fremdtermine | 6→5.8 | 9 |
| S-17 | Liste „reif" (Schwellwert an Posten, Kochtage nahen) → Scheduling schlägt dem Einkaufs-Zuständigen einen Slot vor (nach Arbeitsende, Routine) | 5.5→5.8 | 5 |

**Wissen & Kommunikation**

| ID | Synergie | Module | Phase |
|---|---|---|---|
| S-18 | Anleitung referenziert Vault-Eintrag ohne Inhaltspreisgabe — Auflösung nur mit Vault-Recht („Routerzugang: siehe Vault") | 5.13↔5.11 | 7 |
| S-19 | Generische Objekt-Verknüpfung Rezept↔Anleitung („Pizzaofen anheizen" am Pizzarezept) | 5.2↔5.13 | 7 |
| S-20 | Wochen-Digest als Quer-Artefakt: Essensplan, meine Aufgaben, Challenge-Stand, Wetter-Ausblick, später Salden — eine Mail/Inbox-Karte | 5.12←4/9/16/18 | 8 |
| S-21 | „Heute"-Dashboard als Querschnitts-Startseite: heutiges Essen (+ Koch), meine Tasks, Listen-Stand, Pin-Notiz, ungelesene Briefe, Raum-Ampel — jede Kachel folgt den Modul-Flags | UI-Hub | ab 3, voll 8 |

**Eingang & Konvertierung**

| ID | Synergie | Module | Phase |
|---|---|---|---|
| S-22 | Zuruf-Aktionsketten (5.17): ein Freitext erzeugt verknüpfte Artefakte über Modulgrenzen — inkl. Abhängigkeit Posten→Task (Deo-Referenzfall) | 5.17→5.5/5.6/5.9/5.14 | 4 (Parser), 7 (LLM) |
| S-23 | Konvertieren-Pfade: Notiz → Task/Posten/Anleitung; Brief mit „Kümmerst du dich?"-Knopf erzeugt Task beim Empfänger | 5.14/5.12→5.9 | 7 |
| S-24 | @-Mentions in Kommentaren erzeugen Inbox-Einträge (bereits 5.12 — Katalog-Querverweis) | 5.12 | 7 |

**Bewusste Nicht-Verbindungen (genauso verbindlich):**

- **N-1 Punkte ↛ Geld.** Nie eine Umrechnung, getrennte Ledger (5.9/5.18).
- **N-2 Wearable-Daten ↛ andere Mitglieder.** Rohdaten und Scores sind
  privat und beeinflussen ausschließlich Vorschläge an die eigene Person.
  Keine „Wer hat schlecht geschlafen"-Sicht — auch nicht für Admins.
- **N-3 Vault ↛ LLM/Suche/Logs.** Vault-Inhalte verlassen den Krypto-Pfad
  nie, auch nicht als Zuruf-/Assist-Kontext.
- **N-4 Importierte Fremdrezepte ↛ Teilen** über Haushaltsgrenzen (5.2, Recht).
- **N-5 Kein Geofencing.** Ein grober Haushalts-Standort fürs Wetter, kein
  Geräte-GPS, keine „du bist gerade beim Supermarkt"-Trigger — bewusst
  verworfen (Privatsphäre schlägt Komfort-Gimmick).

---

## 6. Kalender-Interoperabilität

Anforderung: maximale Kompatibilität. Umsetzung gestaffelt nach Aufwand/Nutzen:

| Stufe | Feature | Richtung | Aufwand |
|---|---|---|---|
| 1 | **ICS-Feed-Export** pro Kalender (persönlich & Haushalt) als Secret-URL — abonnierbar in Google/Apple/Nextcloud/Outlook | aus der App raus | klein |
| 2 | **ICS-Datei-Import** (einmalig, inkl. RRULE) | in die App rein | klein |
| 3 | **CalDAV-Client-Sync** (Zwei-Wege-Abo externer Kalender: Nextcloud, iCloud, Google via CalDAV-Endpunkt) — externe Termine erscheinen als eigener Layer und füttern die Scheduling-Engine („belegt") | beidseitig | mittel |
| 4 | **Eigener CalDAV-Server-Endpunkt** (unsere Kalender in Drittclients wie Thunderbird/DAVx⁵ bearbeiten) | beidseitig | groß, optional spät |

RRULE/iCalendar strikt über bewährte Libraries (z. B. `icalendar`, `python-dateutil`/
`recurring-ical-events`), niemals selbst geparst. Zeitzonen: alles UTC in der DB,
Haushalts-TZ fürs Rendering, DST-Tests verpflichtend (klassische Bug-Quelle).

---

## 7. Architektur

> Verbindliche Detail-Spezifikation: **ARCHITECTURE.md** (C4-Modell,
> API-Vertrag, Sync-Protokoll, Qualitäts-Budgets, ADRs). Dieses Kapitel
> bleibt die Kurzfassung.

### 7.1 Überblick

```
[Web-PWA React]      [Android Kotlin/Compose]        (später: iOS)
       \                    /
        \                  /            generierte Clients aus OpenAPI
         ▼                ▼
   ┌─────────────────────────────┐
   │  FastAPI  (modules/*)       │  Auth, REST, SSE/WebSocket
   ├─────────────────────────────┤
   │  Services & Domain-Events   │  Outbox → Worker
   ├──────────┬─────────┬────────┤
   │ Postgres │  Redis  │  S3/   │  Daten · Cache/Queues · Anhänge
   │  (+RLS)  │         │ MinIO  │
   └──────────┴─────────┴────────┘
         Worker (taskiq): Import-Fetch, Nutrition-Mapping, Push,
         Wetter-/Wearable-Sync, ICS/CalDAV-Sync, Event-Verteilung
```

### 7.2 Tech-Stack & Begründung

**Reihenfolge: Web zuerst, dann Android (Vorgabe).**

- **Web:** React + TypeScript + Vite, TanStack Router/Query, Tailwind; PWA mit
  Workbox-Service-Worker; IndexedDB (Dexie) für Offline-Lesen/Abhaken der
  Einkaufsliste. Deckt sich mit vorhandenen Skills und ist für
  einen Web-First-Launch der reifste Weg.
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic, Postgres 18, Redis, taskiq-Worker,
  S3-kompatibler Objektspeicher für Anhänge (Beta: MinIO auf dem Beta-Server; Produktion:
  Hetzner Object Storage). Vorhandener, beherrschter Stack.
- **Android (spätere Phase):** Kotlin + Jetpack Compose nativ, Room (lokale DB),
  WorkManager (Background-Sync), Health Connect SDK; API-Client aus OpenAPI
  generiert. Vorhandene Skills aus dem Android-Setup.
- **Geprüft und verworfen:**
  - *Compose Multiplatform Web:* Web-Target ist weiterhin Beta — keine Basis für
    ein Web-First-Produkt; zusätzlich Canvas-Rendering (SEO/A11y/Bundle-Nachteile).
  - *Flutter:* eine Codebase wäre verlockend, aber Flutter Web rendert ebenfalls
    Canvas-basiert (gleiche Nachteile) und wäre ein kompletter Stack-Neustart ohne
    Not — die vorhandenen React- und Kotlin-Skills decken beide Zielplattformen
    nativ besser ab.
  - *Kotlin Multiplatform nur für Logik:* lohnt erst, wenn Android-Client existiert
    und Logik-Duplikation real wehtut; der OpenAPI-Vertrag minimiert sie ohnehin.

### 7.3 Sync & Offline (Design ab Tag 1, auch wenn die App später kommt)

- **Web: online-first** mit optimistischen Updates (TanStack Query) + begrenztem
  Offline-Modus (Einkaufsliste lesen/abhaken via Dexie-Queue).
- **Android: lokale Datenhaltung (Room) für die wichtigen Module** (Einkaufsliste
  voll offline; Rezepte/Kalender/Tasks lesend gecacht, Änderungen gequeued),
  regelmäßiger Sync (WorkManager) + Sofort-Sync bei App-Open/Push.
- **Protokoll:** Delta-Sync pro Modul: `GET /sync?since=<cursor>` liefert geänderte
  Datensätze + Tombstones; Schreiben idempotent über Client-generierte UUIDs.
  Konflikte: **Last-Write-Wins pro **Feldgruppe** (ARCHITECTURE §10, ADR-003 — der Code merged nur die Felder, die eine Op mitbringt; „pro Feld“ war hier ungenau)** mit Server-Zeitstempel — bewusst kein
  CRDT (Komplexität), und die Datenmodellierung minimiert Konflikte strukturell:
  Einkaufsposten sind eigenständige Zeilen (zwei Leute haken verschiedene Posten
  ab = kein Konflikt), Häkchen ist ein eigenes Feld (Abhaken kollidiert nicht mit
  Umbenennen).
- **Live:** ein SSE/WebSocket-Kanal pro Haushalt für Echtzeit-UI (Liste, Inbox,
  Marketplace); Live ist Komfort, Sync ist Wahrheit (Reconnect = Delta-Sync).

### 7.4 Mandantenfähigkeit

- `household_id` auf jeder fachlichen Zeile; jede Query household-scoped
  (erzwungen über Repository-Basisklasse).
- **Postgres Row-Level-Security als zweite Verteidigungslinie:** Session-Variable
  `app.household_id`, RLS-Policies auf allen Tabellen. Ein vergessener
  WHERE-Filter darf strukturell keine Fremddaten liefern können.
- Personenbezogene Daten, Wearable-Daten und Vault-Ciphertext in klar getrennten
  Tabellen mit eigenem Zugriffspfad (Vorbereitung für Audits/DSFA).

---

## 8. Sicherheitskonzept („Secure by Design", ohne Zero-Knowledge-Anspruch)

**Transport & Sessions**
- TLS only, HSTS, sichere Cookie-Flags (httpOnly, Secure, SameSite=Lax),
  CSRF-Schutz, strikte CSP, Security-Header komplett.
- Sessions: kurzlebige Access-Tokens + Refresh-Rotation mit Reuse-Detection;
  Geräte-Liste mit Remote-Logout im Profil.

**Authentifizierung**
- Passwörter: Argon2id (parametrisiert nach OWASP-Empfehlung), Pwned-Passwords-
  Check beim Setzen. TOTP-2FA; **Passkeys (WebAuthn)** ab V1 — geringe Zusatzkosten
  im Web-First-Stack, starkes Vertrauenssignal.
- Kinder-Logins (PIN) sind auf den Haushalts-Kontext beschränkt, ratenlimitiert,
  ohne Wert außerhalb der App.

**Daten at rest**
- Volume-Verschlüsselung auf Infrastruktur-Ebene + **Anwendungs-Verschlüsselung
  für besonders sensible Spalten** (OAuth-/Wearable-Tokens, API-Keys) mit
  Key in env/Secret-Store, Rotation dokumentiert.
- Vault: clientseitig verschlüsselt (Design in 5.11) — Server hält nur Ciphertext.
- Backups verschlüsselt (restic/age), Restore-Test ist Teil der Done-Kriterien
  der Betriebs-Phase, nicht optional.

**Anwendung**
- Eingaben strikt über Pydantic-Schemas; Datei-Uploads: Typ-/Größen-Limits,
  Bild-Re-Encoding, Anhänge nur über signierte URLs.
- **SSRF-Schutz beim Rezept-Import** (der Server ruft fremde URLs ab!): nur
  http(s), DNS-Auflösung gegen private/Link-local-Ranges geblockt, Redirect-Limit,
  Timeout, max. Response-Größe. Das ist die exponierteste Stelle des Backends.
- Rate-Limiting (Login, Import, API global), Audit-Log für sicherheitsrelevante
  Aktionen (Logins, Rollenwechsel, Vault-Zugriffe, Admin-Korrekturen, Exporte).
- Dependency-Hygiene: Renovate, `pip-audit`/`npm audit` in CI (GitLab CE),
  Container-Scans; Secrets nie im Repo (CI-Variablen).
- Orientierung: **OWASP ASVS Level 2** als Checkliste pro Release.
- **Externer Pentest vor dem kommerziellen Launch** (Budgetposten in Abschnitt 13;
  bis dahin: Selbst-Audit mit ASVS + automatisierte Scans).

---

## 9. Datenschutz & Recht (kommerziell ab Tag 1 = Pflichtprogramm ab Tag 1)

**DSGVO-Pflichten**
- Rechtsgrundlagen je Verarbeitung dokumentiert; **Art.-9-Gesundheitsdaten
  (Wearables) nur mit ausdrücklicher, granularer Einwilligung** (eigener
  Consent-Screen pro Datentyp, widerrufbar, protokolliert).
- **Datenschutz-Folgenabschätzung (DSFA)**: bei Gesundheitsdaten + systematischer
  Verhaltens-Auswertung sehr wahrscheinlich Pflicht → wird als Dokument im Repo
  geführt und vor Launch fertiggestellt.
- Verzeichnis von Verarbeitungstätigkeiten, AV-Verträge mit allen Prozessoren
  (Hoster, Mail, Payment, Open-Meteo-Abo), TOMs dokumentiert.
- **Betroffenenrechte technisch eingebaut:** Daten-Export pro Nutzer und pro
  Haushalt (JSON + Anhänge als ZIP, Art. 20), Account-/Haushalts-Löschung mit
  definierter Kaskade und Fristen (Löschkonzept-Tabelle je Entität), Wearable-
  Rohdaten-Retention konfigurierbar (Default 90 Tage).
- Kinder: Einwilligung der Eltern für unter 14 (AT) im Anlage-Flow, minimale
  Datenerhebung (kein E-Mail-Zwang), keine Wearables, keine Auswertung über das
  Haushalts-Notwendige hinaus.
- EU-Hosting durchgängig (Beta: ein EU-Hoster; Produktion: Hetzner DE/FI).
  Subprozessoren-Liste öffentlich in der Datenschutzerklärung.
- **Betreiber-Grenze (verbindlich):** Betreiber und Support sehen niemals
  Inhalte — ausschließlich Aggregate und Konto-/Abo-Metadaten, technisch
  erzwungen (ARCHITECTURE §8.6). Jeder Support-Zugriff wird auditiert und ist
  für den Betroffenen im Transparenz-Log des eigenen Kontos sichtbar.
- **Login-Telemetrie:** `login_events` speichern Zeitpunkt, Client
  (Web/Android), Erfolg und nur den **Landescode** (aus der IP abgeleitet —
  die IP selbst wird nicht gespeichert). Zweck: Missbrauchserkennung und
  Statistik (berechtigtes Interesse), Retention 90 Tage, in der
  Datenschutzerklärung ausgewiesen.
- **Produkt-Telemetrie:** aggregierte Feature-Nutzungszähler pro Haushalt,
  ohne Inhalte und ohne Profilbildung; Opt-out in den Einstellungen.
  Fehlgeschlagene Sync-Batches werden zur Fehleranalyse 7 Tage als
  Replay-Fixture vorgehalten (haushaltsbezogen, danach automatisch gelöscht).

**Sonstiges Recht & Formales**
- Impressum, Datenschutzerklärung, AGB inkl. Verbraucher-Widerruf für Abos,
  Gesundheits-Disclaimer (Mealplanner/Wearable-Features sind keine medizinische
  oder ernährungstherapeutische Beratung).
- Markenrecherche vor Namensfestlegung (Abschnitt 15 — nicht Teil der
  Veröffentlichung).

---

## 10. Datenmodell-Skizze

Notation: Entität (Schlüsselfelder) — Invarianten kursiv. Vollständiges Schema
entsteht als Alembic-Migrationen + ER-Diagramm in `docs/ARCHITECTURE.md`.

**Identität & Mandant**
- `users` (id, email?, password_hash, totp?, passkeys[], display_name, locale)
- `households` (id, name, settings_json: module_flags, tz, location_coarse,
  market_rules, currency_name)
- `memberships` (user_id, household_id, role: admin|member|child|guest,
  work_hours_json, dietary_prefs_json, joined_at) — *ein User ↔ n Haushalte*
- `invites` (household_id, code, role, expires_at, max_uses)
- `consents` (user_id, scope: tos|privacy|art9_<typ>|child_parental, granted_at,
  revoked_at) — *append-only*

**Küche**
- `ingredients` (id, names_i18n, category, default_unit, conversions_json)
- `ingredient_nutrition` (ingredient_id, source: usda|off|manual, per_100g_json,
  confidence)
- `recipes` (id, household_id, title, servings, steps_md, times, source_url?,
  tags[], photos[])
- `recipe_ingredients` (recipe_id, ingredient_id?, raw_text, qty, unit) —
  *raw_text bleibt immer erhalten (Mapping ist reversibel)*
- `mealplans` (household_id, week) / `mealplan_entries` (day, slot, recipe_id?,
  free_text?, servings_factor, locked)
- `shopping_lists` (household_id, name, category_order[]) /
  `shopping_items` (list_id, label, qty?, unit?, category, checked, checked_by?,
  source: mealplan|manual|basic, created_by) — *Posten = eigenständige Zeile;
  `checked` ist eigenes Feld (Konfliktarmut)*
- `basics` (household_id, label, category, suggest_interval?)

**Aufgaben & Ökonomie**
- `task_templates` (household_id, title, points, duration_est, outdoor: bool,
  rrule?, pool[], rotation: fair|fixed|open)
- `task_instances` (template_id?, household_id, title, due_window, assigned_to?,
  status: open|done|expired, done_at, scheduled_slot?) — *Status-Maschine, keine
  Löschungen*
- `points_ledger` (household_id, from_account, to_account, amount, ref_type,
  ref_id, note?, created_by, created_at) — *append-only; Konten: system,
  member:<id>, escrow:<listing_id>; Salden sind Summen; amount > 0*
- `rewards` (household_id, title, cost, stock?, cooldown?, active) /
  `redemptions` (reward_id, member_id, status: requested|fulfilled, ts)
- `market_listings` (task_instance_id, seller_id, price, status:
  open|accepted|settled|reverted|withdrawn, buyer_id?, ts_*) — *Preis bei
  Erstellung in escrow gebucht; settle erst bei task done*
- `auto_accept_rules` (member_id, template_id|category, max_price, active)
- `rooms` (household_id, name, icon?, decay_days); `task_templates` erhalten
  optional `room_id` — *Raum-Indikator = f(letzte Erledigung, decay_days),
  berechnet, nicht gespeichert*
- Wochen-Challenge: Konfiguration in `households.settings_json`; Wertung wird
  live aus dem Wochen-Ledger berechnet (kein zweiter Zähler in der DB)
- Danke-Punkte: reguläre Ledger-Buchung mit `ref_type=thanks` + Wochen-Cap
- `captures` (household_id, member_id, raw_text, tags[], status:
  proposed|confirmed|dismissed|auto, proposal_json, ts) — *Zuruf-Eingang 5.17*
- `routines` (member_id, name, schedule_rrule, window, lead_minutes) —
  *Kontext-Anker für Zuruf & Scheduling*
- `task_instances.activation_json` (immediate | on_item_checked:<item_id> |
  on_date) + `scheduling_hint` (z. B. before_routine:<id>) — *Aktionsketten*
- `shopping_items.follow_up_json` (zu aktivierender Task) — *Deo-Fall*
- `rewards.kind` (standard | mealplan_wish | custom) — *S-07*
- `events.flags_json` (absence, away_meal, guests_n, guest_prefs[]) — *S-01/08/09*
- `mealplan_entries.cook_member_id?` — *S-03 „Wer kocht heute"*
- `object_links` (from_type, from_id, to_type, to_id, kind) — *generische
  Verknüpfung für S-11/12/18/19; ACL-Prüfung beim Auflösen, nie beim Anlegen*

**Finanzen (Modul 5.18, Phase 13)**
- `expenses` (household_id, payer_id, amount_cents, category?, note,
  receipt_file?, rrule?, ts)
- `expense_shares` (expense_id, member_id, share_cents) — *Σ Shares = Betrag*
- `settlements` (household_id, from_id, to_id, amount_cents, note?, ts) —
  *strikt getrennt vom Punkte-Ledger*

**Kalender**
- `calendars` (owner: member|household, name, color, ics_secret)
- `events` (calendar_id, title, start, end, rrule?, visibility, source:
  local|ics_import|caldav, ext_uid?) — *alles UTC*
- `external_calendar_subscriptions` (member_id, caldav_url, creds_enc, last_sync)

**Kommunikation & Wissen**
- `notifications` (user_id, type, payload_json, read_at?, channels_sent[])
- `comments` (household_id, object_type, object_id, author_id, body_md, ts)
- `letters` (household_id, from_id, to_ids[], subject, body_md, attachment?,
  read_map_json)
- `guides` (household_id, title, body_md, category, tags[], acl_json, version) /
  `guide_attachments` / `contacts` (name, role, phone, email, notes,
  linked_guides[])
- `notes` (household_id, owner_id?, shared: bool, body_md, pinned, archived)

**Integrationen & Betrieb**
- `vault_items` (household_id, label, ciphertext, nonce, acl_json) +
  `vault_keys` (member_id, wrapped_household_key, pubkey, recovery_hash)
- `wearable_connections` (member_id, provider: oura|garmin|healthconnect,
  tokens_enc?, scopes[], status) /
  `wearable_daily` (member_id, date, sleep_score?, readiness?, steps?,
  active_kcal?, rhr?) — *getrennt, eng berechtigt, Retention-Job*
- `weather_cache` (location, date, forecast_json, fetched_at)
- `events_outbox` (id, type, payload, created_at, processed_at?) — *Outbox-Pattern*
- `audit_log` (household_id?, actor, action, object, meta, ts) — *append-only*

**Betreiber & Telemetrie (§11)**
- `operators` (id, email, passkeys[], totp, role: owner|support) — *strikt
  getrennt von `users`*
- `login_events` (user_id, ts, client: web|android, country_code, success) —
  *Retention 90 Tage, keine IP*
- `usage_counters` (household_id, feature, day, count) — *aggregiert, ohne Inhalte*
- `daily_metrics` (date, metric, dims_json, value) — *nächtlicher Rollup für
  die Betreiber-Konsole; die Konsole liest nie Fachtabellen*
- `announcements` (level, title, body_md, active_from, active_to)

---

## 11. Betrieb & Hosting

**Beta (privater Haushalt + Testnutzer): Beta-Server**
- Docker Compose: api, worker, postgres, redis, minio, web (Static via Caddy/
  Cloudflare); Zugang über einen TLS-terminierenden Tunnel/Reverse-Proxy;
  Staging- und Beta-Umgebung getrennt (zwei Compose-Stacks, zwei Subdomains).
- CI/CD über GitLab CE: Pipeline → Tests → Image-Build → Registry →
  Deploy-Job zieht auf den Beta-Server. Migrationen via Alembic im Deploy-Schritt.
- Backups: nächtlicher `pg_dump` + restic (verschlüsselt) auf separates Ziel
  (externes Ziel) **plus WAL-Archivierung** — der Dump ist die
  einfach wiederherstellbare Vollsicherung, die WAL-Kette hält das in ARCHITECTURE zugesagte
  **RPO ≤ 15 min** (Entscheidung 2026-07-31; ein nächtlicher Dump allein bedeutete bis zu 24 h
  Datenverlust). Monatlicher Restore-Test. **Der Verschlüsselungsschlüssel aus `<stack-dir>/.env`
  gehört in den Backup-Umfang** — ohne ihn stellt ein DB-Restore `creds_enc`/`tokens_enc` als
  unlesbaren Ciphertext wieder her.

**Produktion (ab zahlenden Kunden): Hetzner**
- Start: 1× CPX31/CX32 (App+Worker) + Managed-ähnliches Postgres-Setup auf
  eigenem Volume ODER zweiter kleiner Node für DB; Hetzner Object Storage für
  Anhänge; Loadbalancer/Cloudflare davor. Migration vom Beta-Server =
  DB-Dump + Objektkopie + DNS-Switch (Runbook wird in der Betriebs-Phase
  geschrieben und einmal geprobt).
- Monitoring: Uptime-Kuma (extern gehostet, nicht auf sich selbst), Sentry
  (Fehler, Free-Tier reicht lange), strukturierte JSON-Logs, Plausible
  (self-hosted, cookielos) für Web-Analytics.
- E-Mail-Zustellbarkeit: eigene Versanddomain mit SPF, DKIM und DMARC ab dem
  ersten Versand; Bounce-/Complaint-Handling über den Provider.
- Status-Kommunikation: simple Status-Page (z. B. Uptime-Kuma public page).

**Betreiber-Konsole (Backoffice) — das Cockpit des Betreibers**

Harte Grenze zuerst: **Der Betreiber sieht niemals Inhalte** — keine Rezepte,
Notizen, Briefe, Anhänge, Kalender. Das ist technisch erzwungen (eigene
DB-Rollen ohne Leserecht auf Inhaltstabellen, ARCHITECTURE §8.6), nicht nur
organisatorisch. Sichtbar sind ausschließlich Aggregate und
Konto-/Abo-Metadaten; jeder Support-Zugriff ist auditiert und für den
betroffenen Account im Transparenz-Log sichtbar.

- **Geschäfts-KPIs:** aktive Haushalte & Mitglieder, laufende/konvertierte
  Trials, zahlende Abos, MRR/ARR & Churn (aus Paddle-Webhooks gespiegelt),
  Aktivierungs-Funnel (Warteliste → Registrierung → Onboarding fertig →
  Woche-4-aktiv), Retention-Kohorten.
- **Nutzungs-KPIs:** DAU/WAU/MAU, Login-Frequenz und Client-Verteilung
  Web/Android (aus `login_events`), Länder-Verteilung (nur Landescode),
  Feature-Nutzung je Modul aus `usage_counters` — zeigt, was ausgebaut
  gehört und was niemand nutzt (datengetriebene Roadmap).
- **System-Gesundheit:** API-Fehlerrate & P95-Latenzen, Queue-Tiefen,
  Sync-Fehlerquote, Speicher-/Backup-Status, letzte Deploys — erster Blick
  hier, zweiter in Sentry.
- **Support-Werkzeuge:** Suche nach E-Mail/Haushalts-ID → Konto-/Abo-Status,
  Limits, letzte Fehler-Referenzcodes (nur Codes und Typen, nie Inhalte).
  Aktionen: Trial verlängern, Premium-Gutschrift, Verifikations-Mail neu
  senden, Konto entsperren, DSGVO-Export/-Löschung anstoßen — jede Aktion
  mit Pflicht-Begründung ins Audit-Log.
- **Steuerung:** globale Feature-Flags, Ankündigungs-Banner & Release-Notes,
  Wartungsmodus (Read-only-Schalter), Kill-Switch je externem Adapter
  (Wetter, LLM, Oura, CalDAV).
- **Technik:** eigener Bereich `ops.<domain>`, eigener Operator-Login
  (Passkey + TOTP Pflicht, optionale IP-Allowlist), Daten ausschließlich aus
  nächtlichen Rollups (`daily_metrics`), nie aus Live-Queries über Fachdaten.

Ausbau: **v1** (KPI-Kern, Support-Suche, Banner, Flags) in Phase 8 vor der
Closed Beta; **v2** (Abo-/MRR-Sicht, Kohorten) in Phase 12.

---

## 12. Marketing & Go-to-Market

*§12 Marketing & Go-to-Market — nicht Teil der Veröffentlichung.*

Das Produkt ist als EU-gehosteter, werbefreier und fair bepreister Dienst gedacht — ein
Abo pro Haushalt, alle Module, keine Datenverwertung. Marketing- und Launch-Planung sind
nicht Teil dieser Veröffentlichung.

---

## 13. Kosten

*§13 Kosten (Kostenmodell und Wirtschaftlichkeit) — nicht Teil der Veröffentlichung.*

---

## 14. Roadmap (Bau-Reihenfolge bis 0.1 / 0.2)

Kein öffentliches Release vor Fertigstellung (Vorgabe). Die Phasen sind
Bau-Reihenfolge mit Done-Kriterien — jede Phase liefert ein vollständig gebautes
Stück nach diesem Konzept, keine Light-Versionen. Detailschritte entstehen pro
Phase in `Roadmap_to_V0.1.md`.

**Phase 0 — Fundament-Entscheidungen.** Name fixiert (Abschnitt 15),
GitLab-Repo + CI, Projekt-CLAUDE.md, docs-Struktur (ARCHITECTURE, MODULES, ADRs,
BUGLOG), Design-Tokens, `docs/WETTBEWERB.md`, **`UX_KONZEPT.md`**
(Informationsarchitektur, Navigationsmodell, Screen-Inventar je Modul, die
fünf Kern-Flows: Onboarding, Wochenplanung, Einkauf im Laden,
Task-Erledigung, Zuruf — das Schwester-Dokument dieses Konzepts auf
Bildschirm-Ebene). *Done:* CI baut und deployt ein leeres Gerüst auf
Staging; dieses Konzept als v1.0 eingefroren.

**Phase 1 — Plattform-Fundament.** Auth (Argon2id, TOTP, Passkeys), Accounts,
Haushalte, Rollen inkl. Kinder-PIN + Eltern-Consent, Einladungen, Mandanten-RLS,
Outbox/Worker, Notification-Inbox + SSE-Kanal, Audit-Log, OpenAPI-Client-Gen.
*Done:* E2E „Haushalt erstellen → einladen → Rollen wechseln"; RLS-Tests beweisen
Datenisolation zwischen Haushalten; Fehler-Referenzcodes sichtbar in jeder
Fehlermeldung; `login_events` aktiv (nur Landescode).

**Phase 2 — Rezepte + Nutrition-Pipeline.** Kanonische Zutaten (Start-Korpus
~500), Import-Pipeline (JSON-LD → recipe-scrapers → LLM → Review) inkl.
SSRF-Schutz, Nährwertberechnung mit Konfidenz. *Done:* 20 reale Rezept-URLs
(DE/AT + international) importieren zu ≥ 90 % ohne Handarbeit; Stichproben-
Nährwerte plausibel gegen Referenzwerte; 15 eigene Starter-Rezepte (DE/EN)
als Seed-Inhalt verfasst — eigene Texte, ausgelieferte Importe sind tabu
(Audit A-11).

**Phase 3 — Einkaufsliste.** Generierung + Aggregation, Markt-Kategorien, Basics,
kollaborativ live, Web-Offline-Modus (Dexie-Queue). *Done:* zwei Browser haken
parallel ab ohne Verlust; Offline-Abhaken synct nach Reconnect korrekt.

**Phase 4 — Aufgaben + Gamification + Marketplace.** Templates/Instanzen,
Ledger, Belohnungskatalog, Fairness-Konto, Marketplace mit Escrow/Auto-Accept/
Rückfall. *Done:* Property-Tests beweisen Ökonomie-Invarianten (Saldensumme
inkl. Escrow konstant, nie negativ); Marketplace-Statusmaschine vollständig
getestet; **Zuruf-Basis** läuft (Regel-Parser, Routinen, Aktionsketten —
der Deo-Fall E2E ohne LLM).

**Phase 5 — Kalender + Scheduling + Wetter.** Persönlicher + Haushaltskalender
mit Layern, RRULE, ICS-Export/-Import, Scheduling-Engine (Arbeitszeiten, Wetter),
Open-Meteo-Anbindung. *Done:* DST-Testsuite grün; ICS-Feeds in Google/Nextcloud
verifiziert; Vorschläge kommen mit Klartext-Begründung.

**Phase 6 — Mealplanner inkl. Automatik.** Wochenplan-UI, Philosophie-Profile,
Automatik-Engine, Diff-basierte Listen-Regeneration. *Done:* Auto-Wochenpläne
für 3 Profile erfüllen Nährwertziele ±10 % ohne Allergie-Verstöße
(Property-Tests).

**Phase 7 — Briefe + Anleitungen + Notizen + Vault + Zuruf-Vollausbau (LLM).** *Done:* Vault-Kryptodesign
dokumentiert und selbst-auditiert, Recovery-Flow real durchgespielt;
FTS-Suche (deutsch) liefert brauchbare Treffer.

**Phase 8 — Web-Polish + Friends&Family-Beta.** Onboarding, Empty/Loading/
Error-States, A11y, Mobile-Browser-QA, DSGVO-Texte v1, In-App-Feedback →
GitHub-Issues; Beta auf dem Beta-Server. *Done:* Lighthouse ≥ 90/95/95/90; 2–4 echte
Haushalte aktiv; **Betreiber-Konsole v1** live (KPI-Kern, Support-Suche,
Banner, Flags).

**Phase 9 — CalDAV-Sync + Oura-Cloud.** Zwei-Wege-CalDAV-Abos, Oura OAuth2 mit
Art.-9-Consent-Flow, Retention-Jobs. *Done:* Nextcloud- und Google-Sync zwei
Wochen stabil; Oura-Daten fließen nachweisbar ins Scheduling.

**Phase 10 — Android-App.** Kotlin/Compose, Room-Offline (Liste vollständig,
Rest gecacht), WorkManager-Sync, Health Connect, FCM. *Done:* Einkauf im
Flugmodus komplett durchspielbar; Sync-Konflikt-Suite grün; Health-Connect-Daten
sichtbar im Scheduling; Play-Console-Freigabe für Health-Connect-Berechtigungen
(eigener Review-Prozess, Vorlauf einplanen) eingeholt (Audit A-12).

**Phase 11 — Hardening + Recht → Release 0.1.** ASVS-L2-Durchgang, externer
Pentest + Fixes, DSFA fertig, Export/Löschung E2E, Backup-Restore-Probe,
Lasttest. *Done = 0.1:* privater Vollbetrieb + Closed Beta in Wellen.

**Phase 12 — Bug-Hunts/Refactors → Release 0.2 (kommerziell).** Retention
messen, Payment (Paddle), Betreiber-Konsole v2 (Abo/MRR, Kohorten),
Migration Beta-Server → Hetzner, Launch. *Danach:* **Phase 13 — Finanzen-Modul (§5.18)**, Garmin-Cloud-Antrag, eigener
CalDAV-Endpunkt, Kundenkarten-Wallet, iOS-Evaluierung.

**Zuordnung der Übernahmen aus der Wettbewerbs-Analyse:**

| Übernahme | Modul | Phase |
|---|---|---|
| Kochmodus | 5.2 | 2 |
| Schnellkatalog + Reservieren | 5.5 | 3 |
| Wert-Verfall · Danke-Punkte · Wochen-Challenge · Kinder-Wochenziele | 5.9 | 4 |
| Raum-Modell + Heatmap | 5.8/5.9 | 4–5 |
| Slot-Regeln | 5.4 | 6 |
| Dashboard-Pin | 5.14 | 7 |
| Wochen-Digest | 5.12 | 8 |
| Mitglieds-Farben | Design-System | 0 ff. |
| Finanzen-Modul | 5.18 | 13 |
| Kundenkarten-Wallet | 5.5 | nach 0.2 |

*T-Nummern verweisen auf die Wettbewerbs-Analyse vom 10.06.2026; die
Langfassung wird in Phase 0 als `docs/WETTBEWERB.md` ins Repo übernommen
(Audit A-09). Synergien S-01–S-24: Phasen-Zuordnung direkt im Katalog (§5.19).*

---

## 15. Namensvorschläge (international)

*§15 Namensvorschläge — nicht Teil der Veröffentlichung.*

Entschieden ist der Name **Custode** (ku-STO-de, ital. „der Hüter/Hausmeister") — die
Bedeutung ist das Produktversprechen und deckt sich mit Design-Richtung („Ruhige Moderne")
und Prinzip P1. Der Anzeige-Name bleibt über `BRAND_NAME` austauschbar. Der Währungsname
der Gamification („Funken" / EN „Sparks") ist ein Vorschlag (Punkt 17.6).

---

## 16. Übernahmen aus „Daily" (Projekt wird ersetzt)

Geprüft und in dieses Konzept übernommen:
1. **Notizen-Modul** (5.14) — fehlte im neuen Entwurf, war Kern von Daily;
   inkl. „Konvertieren zu…"-Idee als Antwort auf „zu simpel vs. zu komplex".
2. **Lokale LLM-Assistenz** (5.17) — eigene Ollama-Infrastruktur als Feature
   UND Datenschutz-Argument; kein Wettbewerber macht das lokal.
3. **Fairness-Tracking** (5.8) — gleitendes Fairness-Konto für Rotations-Tasks.
4. **Sync-Philosophie** (7.3) — online-first + LWW statt CRDT; Konfliktarmut
   über Datenmodellierung.
5. **Negativ-Erkenntnis:** Name „Daily" ist verbrannt → Abschnitt 15.

Damit ist Daily vollständig in diesem Projekt aufgegangen; das alte Konzept
wird archiviert.

---

## 17. Offene Punkte (vor Phase 0 zu entscheiden, soweit markiert)

| # | Punkt | Default bis zur Entscheidung | Entscheiden bis |
|---|---|---|---|
| 17.1 | Verfallregel | **entschieden:** Wert-Verfall der Aufgabe (−10 %/Tag, min. 50 %), kein Saldo-Abzug | — |
| 17.2 | Nährwert-Ziele | **entschieden:** Haushaltsplan + persönliche Portionsfaktoren | — |
| 17.3 | Vault-Passphrase | **entschieden:** separate Passphrase + Recovery-Code | — |
| 17.4 | Free-Tier-Feinschliff | §3 — nicht Teil der Veröffentlichung | Phase 12 |
| 17.5 | Preis | **entschieden** (§3 — nicht Teil der Veröffentlichung) | — |
| 17.6 | Produktname | **entschieden: Custode**; Währung „Funken"/„Sparks" vorgeschlagen | — |
| 17.7 | Browser-/Geräte-Matrix | **entschieden:** letzte 2 Major Chrome/Firefox/Safari/Edge; Android 10+ | — |
| 17.8 | iOS-Zeitpunkt | **entschieden:** nach 0.2, datengetrieben (Warteliste fragt OS ab) | — |

---

*Begleitdokumente (im selben KONFIG-Ordner): `ARCHITECTURE.md`,
`ENTWICKLUNGSKONZEPT.md`, `Roadmap_to_V0.1.md`, `UX_KONZEPT.md`,
`WETTBEWERB.md` sowie `CLAUDE.md` (Repo-Wurzel). Audit-Kennungen (A-xx/B-xx/C-xx)
verweisen auf das interne Konzept-Audit vom Juni 2026 (nicht im Repo).*
