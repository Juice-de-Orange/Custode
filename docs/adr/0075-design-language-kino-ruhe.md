# ADR-0075 — Designsprache „Kino-Ruhe" (Evolution der „Ruhigen Moderne")

**Status:** beschlossen · **Phase:** 8 (Web-Polish) · **Datum:** 2026-06-30
**Kontext-KONZEPT:** `ENTWICKLUNGSKONZEPT.md` Teil A (Produktprinzipien P1/P8) + A.2
(Gestaltungsrichtung), `UX_KONZEPT.md` §1–§3, **ADR-0006** (Lingui/ICU, i18n ab Tag 1),
**ADR-0007** (Radix-Primitives + Tailwind-Tokens als Design-System-Basis).

## Kontext
Die ursprüngliche Gestaltungsrichtung **„Ruhige Moderne"** (A.2) war richtig gedacht, wurde aber nur
als **Skelett** umgesetzt: die drei Marken-Fonts (Bricolage Grotesque / Inter / IBM Plex Mono) waren
zwar als Tokens deklariert, aber **nie geladen** (alles rendert in der System-Schrift); die warme
Palette und das Signatur-Element **Personen-Faden** waren als Tokens vorhanden, aber **nirgends
verwendet**; es gab **keine Icons** (Emojis als Platzhalter), keine Tiefe, **kein Logo, keinen
Dark-Mode, keine Animation**. Ergebnis: eine faktische Graustufen-Seite mit grünen Links in
System-Schrift — **steril**, obwohl auf dem Papier eine warme Sprache definiert war.

Gleichzeitig liegt eine klare Stil-Präferenz des Eigentümers vor: **hochwertig & durchdacht,
französisches Film-/Editorial-Design, Silhouetten, thematische Landschafts-/Raum-Hintergründe** —
„ansprechend, nicht steril". Das geht bewusst **über** die betont nüchterne „Ruhige Moderne" hinaus.

Projektregel (Prinzip E9, `CLAUDE.md`): *erst Konzept/ADR ändern, dann Code.* Eine getroffene
Designentscheidung wird nicht still überschrieben — sie wird per ADR **abgelöst**.

## Entscheidung
**„Ruhige Moderne" → „Kino-Ruhe" (Cinematic Calm).** Eine **Evolution, kein Bruch**: die gute DNA
bleibt, eine kinematisch-editoriale Schicht kommt hinzu.

**Behalten (DNA):**
- Drei Typo-Rollen (Display = Bricolage Grotesque, Body = Inter mit tabellarischen Ziffern,
  Zahlen-Akzent = IBM Plex Mono) — **jetzt tatsächlich geladen** (self-hosted via `@fontsource`,
  Gewichtsachse, `unicode-range`-Subsets, `font-display: swap`).
- **Personen-Faden** als Signatur (Farbkante an allem, was einer Person gehört); Farbe nie
  alleiniger Bedeutungsträger (immer + Initiale/Label, WCAG 1.4.1).
- Tabellarische Ziffern global (`tnum`); Kontrast-Regeln Audit C-01 (`--bernstein` nur große
  Ziffern/Flächen, `--bernstein-text` für Fließtext; Dark nutzt aufgehellte Akzente).
- „Genau ein orchestrierter Moment" (das Abhaken), sonst dezente 150–200-ms-Transitions;
  `prefers-reduced-motion` respektiert.

**Neu (kinematisch, „durchdacht wild"):**
- **Warme Kino-Farbgradierung** auf der vorhandenen Palette (Lorbeer-Grün, Bernstein-Gold,
  Backstein-Rot = warme Farbwelt). Token-Namen bleiben stabil; additive Tokens für Surfaces,
  Elevation, Scrim, Radius.
- **Dezente Tiefe** (weiche Elevation-Skala) + **Letterbox-Framing** + feines **Film-Korn** an
  Hero-/Szenen-Flächen — Tiefe bleibt sparsam, Trennung weiter primär über Abstand/Hairlines.
- **Thematische Silhouetten-Szenen** je Modul (Landschaft/Raum) als ruhiger Hintergrund von
  Hero- & Empty-States — Küche, Wohnraum, Horizont, Regal/Tresor …
- **Dark „Nacht"-Modus erstklassig** (kinematisch), system-folgend + manuell umschaltbar.
- **Echtes Brand-Mark** (SVG-Logomark + Wortmarke); BRAND_NAME bleibt einzige Text-Quelle
  (`web/src/lib/brand.ts`).
- **Konsistentes Icon-Set** (`lucide-react`, tree-shakeable) statt Emoji-Platzhaltern.

## Constraints (verbindlich)
- **Grafik = leichte SVGs.** Keine fotografischen Raster-Assets; Szenen/Logo/Illustrationen sind
  Vektor (scharf, thembar, Dark-Variante). Lighthouse-Budget **≥ 90/95/95/90** bleibt Ziel;
  **libsodium bleibt Lazy-Chunk** (nicht im Haupt-Bundle); Bundle-Size-Gate (Phase-8-Rest).
- **A11y bleibt AA (WCAG 2.2):** Szenen-Hintergründe immer mit **Scrim** für Textkontrast; Fokus
  sichtbar (`:focus-visible`); Touch-Targets ≥ 44 px; Tastatur-Bedienbarkeit; Trio-Regel je Route.
- **i18n unangetastet:** keine hartcodierten Strings (Keys in `de.ts`+`en.ts`), BRAND_NAME-Regel.
- **Fonts self-hosted** (kein externer Google-Fonts-Request → Best-Practices/Datenschutz).

## Konsequenzen
- A.2 in `ENTWICKLUNGSKONZEPT.md` und das Leitbild in `UX_KONZEPT.md` §1 werden auf „Kino-Ruhe"
  umgeschrieben; das Nav-Modell (§2/§3: ≤5 Einträge, Sidebar/Bottom-Tab, Command-Palette, Inbox,
  Switcher) war bereits spezifiziert und wird jetzt erstmals umgesetzt.
- Umsetzung in Slices (Fundament → Grafik-System → Shell/IA → Screens → Phase-8-Reste); jede Slice
  hält alle CI-Gates grün.
- „Bewusst vermieden" der alten A.2 (Bonbon-Gamification, Neon, Zeitungs-Cosplay) bleibt gültig —
  „Kino-Ruhe" ist hochwertig-filmisch, **nicht** verspielt; Punkte bleiben Währung, kein Konfetti.
- Der Kinder-Modus behält die Richtung (größere Ziele, einfacheres Vokabular) — kein Stilbruch.
