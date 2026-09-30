# ENTWICKLUNGSKONZEPT.md — Der rote Faden

> Gilt für jede Zeile Code, jedes Feature, jede Claude-Code-Session und jede
> Design-Entscheidung. Wenn eine Abkürzung gegen dieses Dokument verstößt,
> ist sie keine Abkürzung, sondern eine Schuld.
> Rangfolge der Dokumente: KONZEPT.md (was & warum) → ARCHITECTURE.md (wie,
> technisch) → dieses Dokument (wie wir arbeiten, immer).

---

## Teil A — Produktprinzipien (UX)

Das Produkt soll sich „durchdachter als die Alternativen" anfühlen. Das
entsteht nicht durch mehr Features, sondern durch acht konsequent
durchgehaltene Prinzipien. Jede neue Sicht und jeder Flow wird vor dem Merge
gegen diese Liste geprüft (Checkliste in Teil D).

**P1 — Ruhe statt Lärm.**
Die App drängt sich nie auf. Notification-Budget: standardmäßig maximal eine
gebündelte Push-Benachrichtigung pro Person und Tag, plus direkte Ereignisse,
die mich persönlich betreffen (jemand kauft mir eine Aufgabe ab, Brief
erhalten). Alles ist bündel- und abschaltbar. Keine Engagement-Tricks, keine
Streak-Angst, keine roten Badges ohne Handlungsbedarf. Der Ton der App ist
ein ruhiger Mitbewohner, kein Vertriebler.

**P2 — Drei-Sekunden-Regel.**
Die häufigsten Handgriffe (Posten abhaken, Posten hinzufügen, Aufgabe
erledigen, Rezept in den Plan ziehen) sind vom Startpunkt in ≤ 2 Taps und
fühlen sich dank Optimistic UI sofort an. Diese Pfade haben e2e-Tests, die
die Tap-Zahl festschreiben — UX-Regression wird zum Testfehler.

**P3 — Erklärbare Automatik.**
Jeder automatische Vorschlag (Mealplan, Scheduling, Rotation) trägt ein
sichtbares „Warum" in Klartext, ist mit einem Tap überschreibbar und pro
Funktion global abschaltbar. Die App ist ein Assistent mit Begründung,
nie ein Orakel.

**P4 — Progressive Offenlegung.**
Ein Einzelhaushalt sieht nichts von Rollen, Marketplace oder Fairness.
Module sind pro Haushalt abschaltbar und verschwinden dann vollständig.
Gute Defaults schlagen Einstellungsseiten; jede neue Einstellung braucht
eine Rechtfertigung, warum kein Default reicht.

**P5 — Graceful Enhancement (verbindlich).**
Wearables, Wetter und KI sind strikt optionale Verfeinerungen. **Jede
Funktion hat einen vollwertigen, gleich gut gestalteten Basis-Pfad ohne
diese Datenquellen.** Technisch erzwungen über Null-Adapter
(ARCHITECTURE §8.3): Fachlogik behandelt „Signal unbekannt" als neutralen
Normalfall. Tests decken immer beide Pfade ab (mit/ohne Enhancement). Die
UI bewirbt Enhancements leise („Mit Wetterdaten plane ich Außenaufgaben
schlauer — verbinden?") und straft das Weglassen nie ab.

**P6 — Offline ist kein Fehlerzustand.**
Kernflüsse (allen voran die Einkaufsliste in der App) funktionieren ohne
Netz vollständig. Sync-Status wird leise kommuniziert (kleines Symbol,
nie Modals). Reconnect ist unsichtbar, Konflikte löst das System nach
ARCHITECTURE §10 — der Nutzer merkt davon im Normalfall nichts.

**P7 — Sofortiger Wert.**
Onboarding-Ziel: In unter 10 Minuten hat ein neuer Haushalt drei importierte
Rezepte, einen ersten Wochenplan-Entwurf und eine Einkaufsliste. Jeder leere
Zustand zeigt den nächsten sinnvollen Schritt, nie nur „Noch nichts hier".

**P8 — Ein Ton.**
Microcopy ist freundlich, knapp und trocken — nie infantil, nie schreiend.
Der Kinder-Modus hat ein eigenes, einfacheres Vokabular und größere
Bedienelemente. Jede nutzerseitige Formulierung durchläuft ein
Microcopy-Review (Teil D). Konsistenz-Bibliothek: ein Datumsformat, ein
Bestätigungs-Pattern, ein Lösch-Pattern — definiert im Design-System,
nirgends improvisiert.

---

## Teil A.2 — Gestaltungsrichtung (visuell)

Abgeleitet aus der Referenz-Präferenz (Siteinspire-Kuration: dort dominieren
die Kategorien *Typographic*, *Minimal*, *Grid Layout* — typografisch
getragene, ruhige, editorial gestaltete Arbeiten) und aus P1/P8. Arbeitstitel
der Richtung: **„Kino-Ruhe" (Cinematic Calm)** — Evolution der ursprünglichen
**„Ruhigen Moderne"** (abgelöst per **ADR-0075**). Die ruhige, typografische
DNA bleibt; hinzu kommt eine kinematisch-editoriale Schicht (Film-Ästhetik,
Silhouetten, dezente Tiefe), weil die nüchterne Erstfassung in der Umsetzung
**steril** wirkte (Fonts nie geladen, warme Palette/Personen-Faden ungenutzt,
keine Grafik/Tiefe/Animation).

**These.** Alle Wettbewerber im Haushalts-Segment sehen aus wie Spielzeug
(Bonbonfarben, Cartoon-Icons, Badges). Wir gestalten das Gegenteil: ein
ruhiges, typografisch und **filmisch** anmutendes Werkzeug, das man gern offen
auf dem Küchen-Tablet liegen lässt — hochwertig und durchdacht, nicht
verspielt. Die Gamification wirkt dadurch erwachsener — Punkte sind eine
Währung, kein Konfetti.

**Kino-Schicht (neu).** Warme Kino-Farbgradierung auf der bestehenden Palette;
**thematische Silhouetten-Szenen** je Modul (Landschaft/Raum als ruhiger
Hintergrund von Hero- und Empty-States, immer mit **Scrim** für AA-Kontrast);
dezente Elevation + **Letterbox-Framing** + feines **Film-Korn** an
Hero-Flächen; **Dark „Nacht"-Modus erstklassig** (system-folgend + manuell);
ein echtes **SVG-Brand-Mark** (BRAND_NAME bleibt einzige Text-Quelle) und ein
konsistentes **Icon-Set** (`lucide`) statt Emoji-Platzhaltern. Grafik bleibt
**leichtgewichtig (SVG)** — Lighthouse-Budget ≥ 90/95/95/90, libsodium lazy.

**Token-Seed (Startpunkt Phase 0, dort verfeinert):**

| Token | Wert | Rolle |
|---|---|---|
| `--kalk` | #FAFAF7 | Grundfläche hell (fast weiß, minimal warm) |
| `--tinte` | #1B1C1A | Text/Primär |
| `--stein` | #8B8D86 | Hairlines/Ränder/Füllungen (Nicht-Text; 3:1 genügt) |
| `--stein-text` | #6B6D64 hell / #8B8D86 dark | Sekundär-**Fließtext** (theme-geschaltet, AA 4.5:1) |
| `--laurus` | #2F5D3A | DER Akzent (tiefes Lorbeer-Grün): Aktionen, Fokus, Marke |
| `--bernstein` | #C98A2B | sparsamster Zweitakzent: Punkte-/Belohnungsmomente |
| `--nacht` | #141513 | Grundfläche Dark Mode (System-Folge) |

Dazu eine abgestimmte 8er-Palette **Personenfarben** (gedeckte Töne, AA-fest
auf hell und dunkel) — die einzige „Buntheit" im Produkt.

**Kontrast-Regeln (Audit C-01):** `--bernstein` (#C98A2B) besteht auf hellem
Grund kein AA für Text — nur für große Ziffern und Flächen zulässig; für
Fließtext gilt die dunklere Variante `--bernstein-text` #8F5E12. **Analog gilt
`--stein` (#8B8D86) nur für Hairlines/Ränder/Füllungen** (Nicht-Text-Kontrast
3:1 genügt), erreicht aber auf hell nur ~3,3:1 und damit **kein AA für Text** —
Sekundär-Fließtext nutzt daher `--stein-text` (hell #6B6D64, theme-geschaltet;
im Dark Mode bleibt es #8B8D86, das dort bereits AA trägt). Dark Mode erhält
aufgehellte Akzentvarianten (≈ `--laurus-dark` #6FA37E), da #2F5D3A auf #141513
zu kontrastarm ist. Farbe ist nie alleiniger Bedeutungsträger: der
Personen-Faden wird immer von Initiale oder Label begleitet (WCAG 1.4.1).

**Typografie (3 Rollen):** Display mit Charakter — *Bricolage Grotesque*
(warm, eigenständig, frei lizenziert) sparsam für Titel und große Momente;
UI/Body — *Inter* (tabellarische Ziffern!); Zahlen-Akzent — *IBM Plex Mono*
für Punkte, Mengen, Salden. Ziffern sind in diesem Produkt Persönlichkeit:
Punkte, Portionen, Salden erscheinen immer tabellarisch/mono — das ist Teil
der Wiedererkennung.

**Signature-Element:** der **Personen-Faden** — eine schmale, durchgehende
Farbkante an allem, was einer Person gehört (Task-Karte, Kalender-Eintrag,
Kommentar, Listen-Häkchen). Eine einzige, konsequent durchgezogene Linie
ersetzt Avatare-Geklingel und macht Zuständigkeit auf einen Blick lesbar.

**Layout:** ruhiges, diszipliniertes Grid; großzügiger Weißraum; Karten mit
**sparsamer** Tiefe (weiche Elevation als Akzent, Letterbox/Korn nur an
Hero-Flächen) — Trennung weiter **primär** über Abstand und Hairlines, Tiefe
ist Würze, keine Inflation; Struktur-Elemente (Eyebrows, Zähler) nur, wo sie
Information tragen.

**Motion:** genau ein orchestrierter Moment — das **Abhaken** (Posten/Task):
eine kurze, physisch glaubwürdige Erledigt-Animation als Belohnung der
häufigsten Handlung. Alles andere: dezente 150–200-ms-Transitions,
`prefers-reduced-motion` respektiert.

**Bewusst vermieden** (weil generisch): Creme-Hintergrund + Serif +
Terracotta-Akzent; Schwarz + Neongrün; Zeitungs-Cosplay mit Hairline-Spalten;
Bonbon-Gamification. Der Kinder-Modus behält die Ruhige Moderne — größere
Ziele, einfacheres Vokabular, etwas mehr `--bernstein` — kein Stilbruch.

---

## Teil B — Engineering-Prinzipien

Die sieben Qualitätsprinzipien aus dem persönlichen Standard, projektkonkret:

**E1 — Lesbarkeit.** Code wird für den Maintainer in zwei Jahren geschrieben.
Sprechende Namen vor Kommentaren; Kommentare erklären *warum*, nie *was*.
Eine Funktion = eine Absicht.

**E2 — Modularität.** Modulgrenzen sind heilig (ARCHITECTURE §4). Der
import-linter ist kein Vorschlag. Wer eine Grenze kreuzen „muss", hat ein
fehlendes Event oder Interface gefunden — das wird gebaut, nicht umgangen.

**E3 — Prüfbarkeit.** Nichts gilt als funktionierend, was kein Test zeigt.
Services sind ohne HTTP/DB testbar (Ports, Fakes). Bugs bekommen erst einen
Regressionstest, dann einen Fix.

**E4 — Robustheit.** Jede externe Grenze (Netz, Datei, LLM, Webhook) wird
als feindlich behandelt: validieren, begrenzen, timeouten, degradieren.
Fehlerpfade sind designte Pfade mit eigener UX, keine Exceptions ins Leere.

**E5 — Einfachheit.** Die langweiligste Lösung, die die Anforderung erfüllt,
gewinnt. Neue Technologie braucht einen ADR mit dem Satz „Das Bestehende
scheitert nachweislich an X". Cleverness ist ein Warnsignal.

**E6 — Explizitheit.** Keine Magie: explizite Transaktionsgrenzen, explizite
Feldgruppen im Sync, explizite Feature-Flags, explizite Annahmen in Doku.
Implizites Verhalten ist ein Bug im Wartezustand.

**E7 — Konsistenz.** Gleiche Probleme werden gleich gelöst — Pattern-Katalog
in `docs/patterns.md` (Pagination, Fehler, Formulare, Jobs, Events). Eine
zweite Lösung für ein gelöstes Problem braucht einen ADR.

Ergänzend:

**E8 — Boring Technology.** Stack-Innovationsbudget ist nahe null; das
Innovationsbudget gehört dem Produkt (siehe ARCHITECTURE-Leitsatz).

**E9 — Das Konzept ist die Quelle der Wahrheit.** Weicht die Realität vom
KONZEPT ab, wird zuerst das KONZEPT (oder ein ADR) geändert, dann der Code.
Stille Drift ist verboten — das ist „Concept First" im Dauerbetrieb.

**E10 — Fehler sind Daten.** Jeder nicht-triviale Bug landet im BUGLOG mit
Symptom → Ursache → Fix → Regressionstest → Lehre. Wiederkehrende Lehren
werden zu Lint-Regeln, Patterns oder Checklisten-Punkten befördert.

**E11 — Sicherheit ist Teil der Definition, nicht Phase.** Jedes Feature
beantwortet im Review drei Fragen: Wer darf das? (AuthZ-Matrix-Zeile)
Was kann ein Angreifer damit? Welche Daten entstehen und wann sterben sie?

---

## Teil C — Arbeitsweise

**Feature-Ritual (jede Einheit Arbeit):**
1. Konzept-Abgleich: Welche KONZEPT-Abschnitte deckt das ab? Lücke → erst
   Konzept-Update.
2. Claude Code im Plan Mode: Plan reviewen, *dann* bauen. Prompts EN,
   Doku/Commits-Beschreibung DE.
3. Bauen in kleinen, lauffähigen Schritten; Tests parallel, nicht danach.
4. Selbst-Review des Diffs (Checkliste Teil D) — generierter Code wird
   gelesen wie fremder Code, denn das ist er.
5. Doku im selben Commit: MODULES/<x>.md, ggf. ADR, CHANGELOG-Eintrag.

**CLAUDE.md-Hierarchie:** Root-CLAUDE.md (Prinzipien, Verweise auf die drei
Dokumente, Tabu-Liste) + pro Modul eine kurze CLAUDE.md (Zweck, Grenzen,
Events, No-Gos). Nach jeder Phase ein strukturierter Audit-Prompt
(Architektur-Treue, Grenzverletzungen, Testlücken) — Befunde ins BUGLOG
oder als Issues.

**Git & Releases:** Trunk-based, Feature-Branches ≤ 2 Tage, Conventional
Commits, Merge nur bei grüner Pipeline. Intern SemVer; Release-Ritual:
Bug-Hunt-Session → BUGLOG-Durchsicht → Tag → Release-Notes. Die 0.x-Regel
aus dem KONZEPT bleibt: kein öffentliches Release vor 0.1-Kriterien.

**Wöchentliches Betriebs-Ritual (ab Beta):** Backup-Restore-Stichprobe
(monatlich voll), Sentry-Triage auf null offene Unbekannte, BUGLOG pflegen,
Dependency-Updates (Renovate-MRs) mergen. Monatlich zusätzlich:
SLO-/Error-Budget-Blick und `pg_stat_statements`-Review (ARCHITECTURE §12);
Budget aufgebraucht ⇒ Feature-Stopp, Stabilisierungs-Woche.

---

## Teil D — Definition of Done (hart, pro Feature)

Ein Feature ist fertig, wenn **alle** Punkte erfüllt sind:

- [ ] Verhalten entspricht KONZEPT (oder KONZEPT wurde zuerst aktualisiert)
- [ ] Tests: Unit für Logik, Integration für Persistenz/Events, e2e wenn
      Nutzer-Flow; Property-Tests bei Invarianten (Ökonomie, Sync, RRULE)
- [ ] Beide Pfade getestet, wenn Enhancement beteiligt (P5: mit & ohne)
- [ ] OpenAPI aktualisiert, Clients regeneriert, oasdiff ohne Breaking
- [ ] AuthZ-Matrix-Zeile ergänzt + Negativtest (falsche Rolle/fremder Haushalt)
- [ ] Empty-, Loading-, Error-Zustand vorhanden (Trio-Regel)
- [ ] A11y: Tastatur-bedienbar, Labels, Kontrast; axe ohne neue Violations
- [ ] i18n: keine hartcodierten Strings, Keys extrahiert
- [ ] Microcopy-Review gegen P8 (Ton, Konsistenz-Patterns)
- [ ] Performance im Budget (ARCHITECTURE §1; EXPLAIN bei neuen Listen-Queries)
- [ ] Logs/Telemetrie: relevante Events ohne PII; Nutzungszähler (aggregiert)
- [ ] Nutzerseitige Fehler tragen Referenzcode + Eintrag im Fehlerkatalog
- [ ] Migrationen expand/contract-konform
- [ ] MODULES-Doku + CHANGELOG aktualisiert; ADR falls Architektur berührt
- [ ] Feature-Flag, falls riskant oder unfertig sichtbar

## Teil E — Teststrategie

Pyramide: viele Unit-Tests (Services, pure Logik) → gezielte
Integrationstests (Repository, Events, RLS-Negativtests mit
Testcontainers-Postgres) → wenige, stabile e2e-Happy-Paths pro Modul
(Playwright) → Property-Tests als Pflicht für: Punkte-Ökonomie
(Saldensumme inkl. Escrow konstant, nie negativ), Sync-Konvergenz
(ARCHITECTURE §10-Matrix), RRULE/DST, Nutrition-Einheitenumrechnung.
Flaky-Politik: ein Test gilt als grün, wenn er 3× hintereinander grün ist;
flaky Tests werden repariert oder gelöscht, nie ignoriert.
Coverage-Politik: kritische Module (economy, market, sync, vault, tenancy)
Branch ≥ 90 %; global ist Coverage ein Indikator, kein Ziel.

## Teil F — Qualitäts-Gates in CI (blockierend)

ruff + mypy --strict · eslint + tsc --strict · pytest/vitest grün ·
oasdiff ohne Breaking · Client-Regen-Diff leer · import-linter
(Modulgrenzen) · trivy ohne HIGH/CRITICAL · gitleaks sauber ·
axe-Kernrouten · Lighthouse-Budgets · Bundle-Size-Budget.
Ein rotes Gate wird nie „temporär" deaktiviert; es wird gefixt oder die
Regel per ADR geändert.
