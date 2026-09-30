# ADR-0062 — `messaging`-Modul (Briefe): Gelesen-Status als eigene Tabelle

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S4
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.12: „Briefe" — kleine asynchrone Nachrichten an den Haushalt, bewusst ruhig inszeniert
(Betreff, Text, optional Anhang), in der Inbox mit **Gelesen-Status**. Das KONZEPT-Datenmodell skizziert
`letters (… to_ids[], … read_map_json)`. Zu entscheiden: Modulschnitt, Empfänger-/Gelesen-Modell.

## Entscheidung
1. **Neues, eigenständiges Modul `messaging`** (technischer Name; KONZEPT §5.12 „Messaging") —
   importiert **nur** `kernel/*`, `messaging.api` ist leer, kein Modul importiert `messaging`.
   import-linter-Contract „messaging must not depend on other modules" (16. Contract). Die spätere
   Notification-Fan-out konsumiert die **`letter.*`-Events**.
2. **Tabelle `letters`** (Migration 0046, HouseholdScoped-Mixin): `from_id`, `to_ids uuid[]`
   (**leer = Rundbrief an alle**, sonst die adressierten Mitglieder), `subject`, `body_md`; RLS
   `household_isolation` (USING + WITH CHECK) + FORCE + Versions-Trigger (ETag).
3. **Gelesen-Status als eigene Tabelle `letter_reads`** statt `read_map_json` (bewusste Abweichung, E9):
   eine **append-only** Zeile je (Brief, Leser), unique `(letter_id, user_id)`. **Begründung:**
   concurrency-sicher (zwei gleichzeitige Leser stören sich nicht — ein `INSERT … ON CONFLICT DO
   NOTHING` statt JSONB-Read-Modify-Write, das clobbern könnte), sauber per Index abfragbar
   (Ungelesen-Zähler, read_count) und RLS-isoliert. Funktional identisch zum `read_map_json`.
4. **„Empfänger" = adressiert oder Rundbrief, nicht der Absender.** Das Öffnen (`GET /{id}`) schreibt
   nur dann eine Read-Zeile, wenn der Leser **Empfänger** ist (Rundbrief **oder** in `to_ids`) und
   **nicht** der Absender. So zählt der `read_count` nur echte Empfänger; der eigene Brief ist nie
   „ungelesen".
5. **HTTP `/v1/letters`** (member): `GET` (Inbox: empfangen + gesendet, neueste zuerst, mit
   `read_by_me`/`read_count`), `GET /unread-count`, `POST` (senden, CSRF), `GET /{id}` (markiert
   gelesen). Online-first (kein Sync-Batch). Events `letter.created`/`letter.read` → SSE-Entity
   `"letters"`.

## Konsequenzen
- **Positiv:** concurrency-sicherer Gelesen-Status ohne Lost-Update; günstige Ungelesen-/Read-Count-
  Abfragen über Index/GROUP BY; einseitige Modulgrenze; Live-Sync über das Event-Registry; Rundbrief
  umgeht den (noch fehlenden) Empfänger-Picker im Web.
- **Abwägung (E9):** **`letter_reads`-Tabelle statt `read_map_json`** — bewusst, dokumentiert; das
  KONZEPT-Feld war eine Skizze, die Tabelle ist robuster. **Rundbrief-Default** in S4: gezielte
  Empfängerauswahl im Web braucht einen Mitglieder-Endpunkt (noch nicht vorhanden) — die API nimmt
  `to_ids` bereits entgegen, das Web nutzt vorerst den Rundbrief.
- **Grenzen:** kein **Anhang/Bild** in S4 (KONZEPT nennt „optional Anhang") — Folge-Slice (braucht
  Blob-Storage-Anbindung wie das Rezept-Foto); keine Antwort-Threads (Briefe sind bewusst flach);
  Notification-Fan-out (Web Push/E-Mail-Digest) = eigener späterer Slice auf den `letter.*`-Events.

## Alternativen
- **`read_map_json` auf der Letter-Zeile (KONZEPT-Skizze):** verworfen — Read-Modify-Write des JSONB ist
  bei parallelen Lesern lost-update-anfällig und schlechter abfragbar; die Read-Tabelle ist robuster.
- **Pflicht-Empfänger (kein Rundbrief):** verworfen für S4 — ohne Mitglieder-Picker im Web unbenutzbar;
  der Rundbrief (leeres `to_ids`) ist der häufige Haushaltsfall und sofort nutzbar.
- **Kommentare/Notifications gleich mitbauen:** verschoben — eigene Bausteine (§5.12 Ebenen 1+2); der
  Brief ist Ebene 3 und steht für sich; die Events sind die Naht für die Notifications.
