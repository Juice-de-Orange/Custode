# Modul `links`

**Status:** in Arbeit · **Phase:** 7 · **KONZEPT:** §5.12 (Objekte verbinden)

## Zweck & Verantwortung
**Generische, richtungsunabhängige Verknüpfungen** zwischen beliebigen Objekten (Rezept↔Anleitung,
Aufgabe↔Anleitung, Notiz↔Anleitung). P7-S8 ist das **Fundament**: zwei `(type, id)`-Endpunkte +
`relation` — **kein** modulübergreifender FK. Objekt-Picker, ACL und Anhänge folgen in späteren
Slices. Importiert **nur** `kernel/*`; kein Modul liest seine Tabelle.

## Datenobjekte (Migration 0049, ADR-0066)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `object_links` | id; `src_type`/`src_id` + `dst_type`/`dst_id` (kanonisch geordnet, nacktes UUID + ≤40-String-Typ, kein FK); `relation` (≤40); `created_by`; `version` (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |

Partial-Indizes `ix_object_links_src`/`_dst` auf beide Endpunkte (Hot-Lookup „alle Links eines
Objekts"). Partial-Unique-Index `ux_object_links_pair` auf
`(household_id, src_type, src_id, dst_type, dst_id, relation) WHERE NOT deleted` (keine symmetrischen
Duplikate). RLS-Negativtest (`test_links_rls.py`: A↛B→0, WITH CHECK).

## Kanonisierung & Idempotenz (ADR-0066)
Die Endpunkte werden serverseitig geordnet (kleinerer `(type, str(id))` → `src`), sodass `(a, b)`
und `(b, a)` **eine** Zeile ergeben. Ein zweites Verknüpfen desselben Paares mit derselben `relation`
liefert die bestehende Zeile (idempotent, kein Fehler). Selbst-Verknüpfung (`a == b`) → 422.

## Generische Referenz (ADR-0066)
`*_type` ist ein String, `*_id` ein nacktes UUID. So kennt `links` **keines** der verknüpften Module
(und umgekehrt); ein neuer verknüpfbarer Objekttyp braucht **null** Backend-Änderung. Keine
referenzielle Integrität (verwaiste Links bei Objekt-Löschung möglich — Aufräumen via
`*.deleted`-Events = später).

## Schreibpfad
- **Online-first**, kein Sync-Batch. Soft-Delete. **Entkoppeln darf jedes Mitglied** (member/admin) —
  Links sind geteilte Haushalts-Metadaten, kein autorgebundener Inhalt.

## Schnittstellen (HTTP, `/v1/links`)
- `GET ?object_type=&object_id=` (member) → `list[LinkResponse]` (alle Links die das Objekt berühren,
  älteste zuerst; Endpunkte kanonisch).
- `POST` (member/admin, CSRF, 201) → `LinkResponse`. Endpunkte werden kanonisiert; idempotent.
- `DELETE /{id}` (member/admin, CSRF, 204) → Soft-Delete (404 wenn weg).
- **Cross-Modul:** **keins** — `links.api` ist leer; Reaktion über `link.*`-Events.

## Events
- **publiziert:** `link.created`, `link.deleted` → SSE-Entity `"links"`.
- **abonniert (Reaper, P7-S20):** `recipe.deleted` · `note.deleted` · `guide.deleted` →
  `service.purge_for_object` soft-deletet alle Links mit dem gelöschten Objekt an **einem** Endpunkt.
  Handler am Worker-Composition-Root registriert (kein Kernel-Import), Event nur per Name gematcht
  (kein Fremdmodul-Import), idempotent. (`task` ausgeklammert wie bei comments.)

## Web
Wiederverwendbare `LinksPanel`-Komponente (`web/src/links/panel.tsx`) — erstmals an der
Anleitungs-Seite (`/guides`) eingebettet (`objectType="guide"`); an Rezepten/Tasks/Notizen
nachrüstbar. **Objekt-Picker (P7-S19):** statt einer rohen UUID wählt man das Ziel über einen
Typ-Filter + ein **Namens-Dropdown** der vorhandenen Objekte dieses Typs (`web/src/links/objects.ts`
`useObjectOptions`, reine Helfer `pickCandidates`/`resolveLabel`); das eigene Objekt ist
ausgeschlossen (Self-Link = 422). Bestehende Verknüpfungen werden mit **Namen** statt Kurz-ID
angezeigt (Fallback Kurz-ID bei seit gelöschtem Ziel).

## Tests
- `test_links_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_links_http.py` — Verknüpfen + Lesen von beiden Endpunkten; richtungsunabhängige Idempotenz;
  Selbst-Link → 422; Entkoppeln; fremder Haushalt sieht denselben object_id nicht (RLS).
- `web/src/test/links-objects.test.ts` — reine Picker-Helfer: `pickCandidates` (Self-Ausschluss,
  unbekannter Typ → leer), `resolveLabel` (Treffer / null bei gelöschtem Ziel).
- `test_reaper_orphans.py` — Reaper-E2E (P7-S20): Anleitung löschen → Outbox treiben → Link soft-
  deletet (gemeinsam mit dem comments-Reaper geprüft).

## Offene Punkte (spätere Slices)
- **ACL**, **Anleitung↔Vault ohne Inhalt**, Volltextsuche im Picker (statt einfachem Dropdown),
  **Task-Instanz-Reaper** (sobald ein Instanz-Lösch-Event existiert).
