# ADR-0065 — `comments`-Modul: generische Threads via (object_type, object_id)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S7
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.12 (Messaging, Ebene 2): **Kommentare an Objekten** — Threads an Rezepten, Tasks, Events,
Listen, **Anleitungen**, mit @-Mentions. Datenmodell-Skizze: `comments (household_id, object_type,
object_id, author_id, body_md, ts)`. Zu entscheiden: Wie referenzieren Kommentare „beliebige" Objekte,
ohne die Modulgrenzen zu sprengen?

## Entscheidung
1. **Neues, eigenständiges Modul `comments`** (importiert **nur** `kernel/*`, `comments.api` leer,
   kein Modul importiert `comments`). import-linter-Contract „comments must not depend on other
   modules" (18. Contract). Der @-Mention-/Notification-Fan-out (später) konsumiert die
   **`comment.*`-Events**.
2. **Generische Referenz `(object_type, object_id)`** statt eines FK pro Zieltyp: `object_type` ist ein
   **String-Diskriminator** (`"guide"`/`"recipe"`/`"task"`/…), `object_id` ein **nacktes UUID** —
   **kein modulübergreifender FK**. So muss `comments` **keines** der kommentierten Module kennen (und
   umgekehrt). Partial-Index auf `(object_type, object_id) WHERE NOT deleted` für den Hot-Lookup
   „alle Kommentare an diesem Objekt".
3. **Tabelle `comments`** (Migration 0048, HouseholdScoped-Mixin): RLS `household_isolation` (USING +
   WITH CHECK) + FORCE + Versions-Trigger. **RLS-Negativtest** (A↛B→0). Threads werden **älteste
   zuerst** gelistet.
4. **AuthZ:** Lesen jedes Mitglied; Posten member/admin + CSRF; **Löschen nur der Autor** (sonst 403),
   Soft-Delete. (Kein Editieren in S7 — Kommentare sind kurzlebig; Edit/If-Match = später bei Bedarf.)
5. **HTTP `/v1/comments`:** `GET ?object_type=&object_id=` (Thread), `POST`, `DELETE /{id}`. Web: eine
   **wiederverwendbare** `CommentThread`-Komponente, erstmals an der Anleitungs-Seite eingebettet
   (`objectType="guide"`).

## Konsequenzen
- **Positiv:** ein einziges Kommentar-Modul für **alle** Objekttypen ohne Kopplung; neue kommentierbare
  Objekte brauchen **null** Backend-Änderung (nur ein `object_type`-String im Web); RLS-isoliert; Index
  auf dem Diskriminator-Paar = schnelle Threads; Live-Sync über `comment.*`-Events; wiederverwendbare
  Web-Komponente.
- **Abwägung (E9):** **keine referenzielle Integrität** (object_id zeigt „nackt" auf ein Objekt; ein
  gelöschtes Objekt lässt verwaiste Kommentare zurück) — bewusst, der Preis für die Entkopplung; ein
  späterer Reaper/Cascade über die `*.deleted`-Events kann aufräumen. **@-Mentions + Notifications**
  und das **Editieren** sind Folge-Slices.
- **Grenzen:** keine Validierung, dass `object_id` im Haushalt existiert (RLS schützt nur die
  Kommentar-Zeile selbst) — ein nicht-existentes Objekt bekommt einfach einen leeren/„toten" Thread;
  unkritisch.

## Alternativen
- **FK/Join-Tabelle je Zieltyp** (recipe_comments, task_comments, …): verworfen — N Tabellen + N
  Endpunkte, Kopplung, viel Boilerplate; der generische Diskriminator ist Standard für „comments
  überall".
- **Kommentare im jeweiligen Modul speichern:** verworfen — verteilt dieselbe Logik N-fach und bricht
  „ein Inhaltstyp = ein Modul".
- **Polymorpher FK mit DB-Constraint:** verworfen — Postgres hat keinen nativen polymorphen FK; ein
  String-Diskriminator + Index ist der pragmatische, entkoppelte Weg.
