# ADR-0066 — `object_links`: generische, richtungsunabhängige Verknüpfungen

**Status:** beschlossen · **Phase:** 7 (P7-S8) · **Datum:** 2026-06-24
**Kontext-KONZEPT:** §5.12 (Objekte verbinden), Roadmap Phase 7 (`object_links`)

## Kontext
Anleitungen, Rezepte, Aufgaben und Notizen sollen sich gegenseitig referenzieren können
(„diese Anleitung gehört zu jenem Rezept", „diese Aufgabe verweist auf jene Anleitung"). Die
Roadmap nennt explizit `object_links` (Rezept↔Anleitung, Aufgabe↔Anleitung, Anleitung↔Vault ohne
Inhalt). Gesucht ist ein Mechanismus, der **kein** Modul zwingt, ein anderes zu kennen, und der
bei neuen verknüpfbaren Objekttypen **null** Backend-Änderung kostet — analog zu `comments`
(ADR-0065).

## Entscheidung
Ein **eigenständiges Modul `links`** mit einer Tabelle `object_links`. Jede Verknüpfung hat **zwei
Endpunkte**, jeder Endpunkt ein `(type, id)`-Paar: `type` ist ein String-Diskriminator
(`"recipe"`/`"task"`/`"note"`/`"guide"`…), `id` ein **nacktes UUID** — **kein** modulübergreifender
FK. Dazu eine `relation` (Default `"related"`).

**Richtungsunabhängigkeit + Idempotenz:** Die Endpunkte werden serverseitig **kanonisch geordnet**
(der kleinere `(type, str(id))` landet in `src`, der größere in `dst`). Damit kollabieren `(a, b)`
und `(b, a)` zu **einer** Zeile; ein Partial-Unique-Index
`(household_id, src_type, src_id, dst_type, dst_id, relation) WHERE deleted_at IS NULL` verhindert
symmetrische Duplikate. Ein zweites Verknüpfen desselben Paares liefert die bestehende Zeile zurück
(idempotent, kein Fehler). Selbst-Verknüpfung (`a == b`) → 422.

**Lesen:** `GET /v1/links?object_type=&object_id=` liefert **alle** Verknüpfungen, die ein Objekt
berühren (auf `src`- **oder** `dst`-Seite). Die Web-Schicht rechnet den „anderen Endpunkt" relativ
zum betrachteten Objekt aus (`otherEndpoint`).

**Schreiben:** Online-first (kein Sync-Batch), Soft-Delete. **Entkoppeln darf jedes Mitglied**
(member/admin) — Verknüpfungen sind geteilte Haushalts-Metadaten, kein autorgebundener Inhalt (anders
als `comments`, wo nur der Autor löscht).

## Konsequenzen
- **Plus:** Neue verknüpfbare Objekttypen brauchen **null** Backend-Änderung; `links` kennt kein
  Modul, kein Modul kennt `links` (19. import-linter-Contract „links must not depend on other
  modules"). Quermodul-Reaktion nur über `link.*`-Events.
- **Minus:** Keine referenzielle Integrität — verwaiste Verknüpfungen nach Objekt-Löschung sind
  möglich. Aufräumen über `*.deleted`-Events ist ein **späterer** Slice (Reaper). Bis dahin filtert
  die UI tote Endpunkte tolerant (zeigt Typ + gekürztes UUID).
- **Minus:** Ohne Objekt-Picker wird der Ziel-Endpunkt vorerst als Typ + ID eingegeben (Fundament);
  ein echter Picker (Suche/Auswahl) folgt.
- RLS `household_isolation` (USING + WITH CHECK) + FORCE + Versions-Trigger wie bei jeder Fachtabelle;
  RLS-Negativtest (A↛B→0).

## Alternativen
- **FK je Beziehungstyp** (z. B. `guide_id` an `recipes`): bricht Modulgrenzen, skaliert nicht mit
  jeder neuen Paarung. Verworfen.
- **Gerichtete Kante ohne Kanonisierung:** erlaubt `(a,b)` und `(b,a)` als Duplikate; Symmetrie
  müsste in jeder Query nachgebaut werden. Kanonische Ordnung ist einfacher und duplikatfrei.
