# ADR-0061 — Notiz „Konvertieren-zu Aufgabe": synchron via tasks.api

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S3
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5: Notizen sollen sich **„Konvertieren-zu"** anderen Objekttypen lassen (Notiz → Task/Rezept/…).
Der erste, häufigste Fall ist **Notiz → Aufgabe** („das muss ich erledigen"). Zu entscheiden: Wer legt
die Aufgabe an, über welchen Pfad, und was passiert mit der Notiz.

## Entscheidung
1. **Synchron via `tasks.api.create_personal_task`** in derselben Transaktion — derselbe sanktionierte,
   einseitige Cross-Modul-Pfad wie `capture → tasks.api` (ADR-0038) und `mealplanner → tasks.api`
   (ADR-0053). `tasks` bietet die primitiv-argumentige Naht (points 0, KONZEPT §5.6/5.9) — `notes` muss
   **keine** tasks-Schemas importieren.
2. **import-linter:** Der notes-Contract erlaubt nun `tasks.api`, verbietet weiterhin dessen Interna
   (`tasks.service/models/router/schemas`) und alle anderen Module. Name → „notes uses only tasks public
   api". Einseitig (`tasks` kennt `notes` nicht). Weiterhin **15 Contracts**.
3. **Non-destruktiv:** die Aufgabe bekommt den **Titel** der Notiz, zugewiesen an den Auslöser; die
   **Notiz bleibt** (Konvertieren = „eine Aufgabe daraus erzeugen", nicht „die Notiz verschieben").
   `POST /v1/notes/{id}/to-task` (member/admin, CSRF, 201) → `{task_id, title}`; 404 wenn die Notiz weg
   ist. Keine Migration.
4. **Nur Titel → Task-Titel in S3** (kein Body-Übertrag in eine Task-Beschreibung — `tasks` hat keine
   Beschreibungs-Spalte über `create_personal_task`). Reicherer Übertrag (Body → Task-Notiz, Anhänge,
   `object_link` Notiz↔Task) ist ein Folge-Slice.

## Konsequenzen
- **Positiv:** liefert den häufigsten „Konvertieren-zu"-Fall mit einer bereits getesteten Naht; atomar +
  sofort sichtbar (das `task.created`-Event aktualisiert die Aufgabenliste live); einseitige Modulgrenze
  gewahrt; keine Migration.
- **Abwägung (E9):** KONZEPT-„Konvertieren-zu" ist allgemeiner (Notiz↔Task/Rezept, ggf. mit `object_link`
  + Übernahme/Archivierung). S3 liefert **Notiz → Task, non-destruktiv, nur Titel** — bewusst klein;
  weitere Zieltypen und der persistente Link sind Folge-Slices.
- **Grenzen:** kein gespeicherter Notiz↔Task-Link (die Aufgabe „weiß" nicht, dass sie aus einer Notiz
  kam) — wie bei den anderen `create_personal_task`-Konvertierungen; der Link kommt mit `object_links`.

## Alternativen
- **Notiz beim Konvertieren soft-löschen/archivieren:** verworfen für S3 — datenverlust-nah und
  überraschend; non-destruktiv ist sicherer (der Nutzer löscht die Notiz bei Bedarf selbst).
- **Rein eventgetrieben** (`note.*`-Handler legt die Aufgabe an): verworfen — die Konvertierung ist eine
  explizite Nutzeraktion; synchron ist atomar + sofort sichtbar.
- **Body in eine Task-Beschreibung übertragen:** verschoben — `tasks` hat dafür (noch) keine Spalte;
  erst mit reicherem Task-Modell / `object_links` sinnvoll.
