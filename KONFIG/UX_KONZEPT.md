# UX_KONZEPT — Custode

> Schwester-Dokument zu KONZEPT auf Bildschirm-Ebene. Setzt die Produktprinzipien
> P1–P8 und die Gestaltungsrichtung „Kino-Ruhe" (ENTWICKLUNGSKONZEPT A.2, ADR-0075)
> in Navigation, Screens und Flows um. Wireframe-/Pixeltiefe entsteht iterativ
> mit den Design-Tokens; dieses Dokument legt Struktur und Verhalten fest.

## 1. Leitbild
Custode ist der stille Hausmeister: ruhig, typografisch, erwachsen — und
**filmisch**. Die UI drängt nie, erklärt jede Automatik, und zeigt im Zweifel
weniger; wo sie zeigt, tut sie es hochwertig: editoriale Typografie, warme
Kino-Farben, ruhige **Silhouetten-Szenen** (Landschaft/Raum passend zum Modul)
hinter Hero- und Empty-States. Bunt ist nur der Personen-Faden. Eine
orchestrierte Animation (das Abhaken), sonst dezent. Hochwertig & durchdacht,
nie verspielt (ADR-0075).

## 2. Informationsarchitektur

**Primär-Navigation (max. 5 Einträge, rollen-/flag-abhängig):**
1. **Heute** (Dashboard, Startseite)
2. **Essen** (Rezepte + Wochenplan + Einkaufsliste als Tab-Gruppe)
3. **Aufgaben** (Liste + Kalender-Ansicht + Marketplace, flag-abhängig)
4. **Haushalt** (Mitglieder, Anleitungen, Vault, Finanzen — flag-abhängig)
5. **Profil/Mehr** (Einstellungen, Wearables, Briefe, Notizen, Hilfe)

Einzelhaushalt sieht 3–4 Einträge (kein Marketplace, keine Fairness). Module
folgen `households.settings_json.modules`; abgeschaltetes Modul = unsichtbar.

**Globale Elemente:**
- **Palette** (`Strg/Cmd+K` Web, FAB Mobile): Suche + Zuruf in einem Eingang.
- **Inbox** (Glocke): Notifications, Briefe, ungelesene Erwähnungen.
- **Haushalts-Umschalter** (für Multi-Haushalt-Nutzer).
- **Sync-/Offline-Indikator**: leise, nie Modal.

## 3. Navigationsmodell
- Web: persistente Seitennavigation (Desktop) / Bottom-Tab (Mobile-Browser).
- Tiefe maximal 3 Ebenen (Bereich → Liste → Detail). Detail bevorzugt als
  Panel/Sheet über Kontext, nicht als Vollseiten-Sprung.
- Jede Route liefert Empty-, Loading- und Error-Zustand (Trio-Regel).
- Zurück/Deep-Link-fest (TanStack Router, typisierte Routen).

## 4. Screen-Inventar (je Modul, V1)

**Heute:** Tageskarten — heutiges Essen (+ wer kocht), meine fälligen Aufgaben,
Einkaufslisten-Kurzstand, gepinnte Notiz, ungelesene Briefe, Raum-Ampel
(flag). Jede Kachel folgt Modul-Flags; leere Kacheln verschwinden.

**Rezepte:** Galerie (Karten) · Detail (Zutaten/Schritte/Nährwerte/Quelle) ·
Editor · Import-Review · Kochmodus (Vollbild, Schritt-Fokus).

**Wochenplan:** Wochenraster (Slots) · Rezept-Picker (Drag&Drop) ·
Automatik-Dialog (Profil + Slot-Regeln, Vorschau mit Begründung).

**Einkaufsliste:** Liste (kategoriesortiert, Abhaken) · Schnellkatalog
(Kacheln, Kachel/Liste-Toggle) · Mehrlisten-Wechsler.

**Aufgaben:** Meine Aufgaben (heute/Woche) · Haushalts-Board · Template-Editor
(Admin) · Raum-Heatmap (flag) · Fairness-Übersicht (flag).

**Marketplace (flag):** Angebote · Listing erstellen (Preis, Vorschau) ·
Auto-Accept-Regeln.

**Belohnungen:** Katalog · Einlösen · Admin-Katalogpflege · Wochen-Challenge-
Stand (flag).

**Kalender:** Tag/Woche/Monat/Agenda · Layer-Umschalter · Event-Editor (RRULE,
Sichtbarkeit, Flags).

**Anleitungen:** Suche/Kategorien · Artikel · Editor · Kontakte.

**Vault (flag):** Liste · Eintrag (entsperrt) · Passphrase-/Recovery-Setup.

**Finanzen (flag, später):** Ausgaben · Salden „wer schuldet wem" · Kassensturz.

**Briefe/Notizen:** Inbox/Verfasser · Notiz-Editor · Pin-Verwaltung.

**Profil & Einstellungen:** Profil/Arbeitszeiten/Routinen · Präferenzen/
Allergien · Benachrichtigungen · Wearables (Consent je Typ) · Haushalt &
Module (Admin) · Abo · Datenschutz/Export/Papierkorb.

**Onboarding:** 6 Schritte (Konto → Haushalt+Preset → Einladen → 3 Rezepte →
Wochenplan → Einkaufsliste).

**Betreiber-Konsole** (eigene `/ops`-App, nicht Teil der Nutzer-Navigation).

## 5. Die fünf Kern-Flows (mit P-Bezug)

**F1 Onboarding (P7, < 10 min):** Registrieren → Haushalt benennen + Preset
(Solo/Familie/WG setzt Flags) → optional einladen → 3 Rezepte (Import oder
Starter) → „Wochenplan erstellen" (Automatik-Vorschau) → Einkaufsliste sehen.
Jeder Schritt überspringbar; Fortschritt sichtbar; Ende = nutzbares Produkt.

**F2 Wochenplanung (P3):** Essen → Wochenplan → „Automatisch füllen" → Profil +
Slot-Regeln wählen → Vorschau mit Begründung je Slot → einzelne „neu würfeln"
oder per Drag ersetzen → bestätigen → Diff-Hinweis „X Posten zur Liste?".

**F3 Einkauf im Laden (P2, P6):** Einkaufsliste öffnen (offline ok) →
kategoriesortiert → 1-Tap abhaken (optimistic, Abhak-Animation) →
Schnellkatalog für spontane Posten → Reservieren bei Parallel-Einkauf →
Sync läuft leise im Hintergrund.

**F4 Aufgabe erledigen (P2, P1):** Heute/Aufgaben → Karte → „Erledigt" (1 Tap,
Punkte gutgeschrieben, Animation) → bei Engpass optional „verkaufen" (S-10) →
Fairness/Wochen-Challenge aktualisiert leise.

**F5 Zuruf (P2, P3):** Palette öffnen → Freitext „Deo für die Arbeit besorgen"
→ Vorschlagskarte (Posten „Deo" + Folge-Task „in den Rucksack", Begründung) →
1 Tap bestätigen → später im Laden abhaken aktiviert den Task zur richtigen
Zeit. Ohne LLM: landet als „Unsortiert" mit 1-Tap-Triage.

## 6. Zustände, Fehler, Leere
- **Fehler:** menschliche Meldung + Handlungsoption + kopierbarer
  Referenzcode (nie Stacktrace). Offline ist Zustand, kein Fehler.
- **Leere:** zeigt den nächsten sinnvollen Schritt, nie nur „nichts da".
- **Laden:** Skeletons statt Spinner, wo möglich; optimistic bei Top-Aktionen.
- **Sync/Konflikt:** im Normalfall unsichtbar; bei echtem Konflikt klare,
  seltene Rückfrage.

## 7. Barrierefreiheit & Responsiv (WCAG 2.2 AA)
Vollständige Tastatur-Bedienung der fünf Flows; Farbe nie alleiniger
Bedeutungsträger (Personen-Faden + Initiale/Label); Kontrast-Regeln aus
ENTWICKLUNGSKONZEPT A.2; `prefers-reduced-motion`; Touch-Ziele ≥ 44 px
(Kochmodus größer); Mobile-Browser ist gleichwertig, nicht Beiwerk.

## 8. Kinder-Modus
Eigene, reduzierte Sicht: große Aufgaben-Karten, einfacheres Vokabular,
Wochenziel mit Fortschrittsbalken, eigene Belohnungs-Sicht. Gleiche
Gestaltungsrichtung (kein Stilbruch), nur ruhiger und größer.

## 9. Offene UX-Punkte (historisch — alle in der jeweiligen Phase entschieden)
- Wochenplan-Automatik-Vorschau: Begründungstiefe vs. Ruhe — entschieden in
  Phase 6 (Würfeln/Auto-Planer mit knapper Begründung, s. CHANGELOG).
- Schnellkatalog-Kategorisierung: Lernkurve vs. Vorhersagbarkeit — entschieden
  in Phase 3 (kuratierter Schnellkatalog + Haushalts-Basics).
- Heatmap-Darstellung Räume: Ampel vs. Verlauf — entschieden in Phase 5
  (Ampel-Status je Raum).
