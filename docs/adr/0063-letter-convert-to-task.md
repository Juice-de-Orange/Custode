# ADR-0063 — Brief „Kümmerst du dich?" → Aufgabe: synchron via tasks.api

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S5
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.12 / Roadmap (Briefe): „… **„Kümmerst du dich?"→Task**". Ein Brief soll sich direkt in eine
**Aufgabe** überführen lassen — der Empfänger nimmt das Anliegen an. Zu entscheiden: Wer legt die
Aufgabe an, über welchen Pfad, an wen, und was passiert mit dem Brief.

## Entscheidung
1. **Synchron via `tasks.api.create_personal_task`** in derselben Transaktion — derselbe sanktionierte,
   einseitige Cross-Modul-Pfad wie `capture/mealplanner/notes → tasks.api` (ADR-0038/0053/0061). `tasks`
   bietet die primitiv-argumentige Naht (points 0); `messaging` muss **keine** tasks-Schemas importieren.
2. **import-linter:** Der messaging-Contract erlaubt nun `tasks.api`, verbietet weiter dessen Interna
   (`tasks.service/models/router/schemas`) und alle anderen Module. Name → „messaging uses only tasks
   public api". Einseitig (`tasks` kennt `messaging` nicht). Weiterhin **16 Contracts**.
3. **Zugewiesen an den Auslöser, non-destruktiv:** die Aufgabe bekommt den **Betreff** des Briefs als
   Titel, zugewiesen an den **aufrufenden Nutzer** (der Empfänger, der „sich kümmert"); der **Brief
   bleibt** (Konvertieren = „eine Aufgabe daraus erzeugen", nicht den Brief verschieben).
   `POST /v1/letters/{id}/to-task` (member/admin, CSRF, 201) → `{task_id, title}`; 404 wenn weg.
   Keine Migration.
4. **Schema-Name `LetterToTaskResult`** (nicht `ToTaskResult`) — `notes` exportiert bereits ein
   `ToTaskResult` (ADR-0061); gleichnamige OpenAPI-Schemas kollidieren im generierten Web-Client
   (würden voll-qualifiziert/umbenannt). Eindeutiger Name hält den Client sauber (Lehre aus der
   `SlotResponse`-Kollision, P6).

## Konsequenzen
- **Positiv:** liefert den „Kümmerst du dich?"-Fall mit einer bereits getesteten Naht; atomar + sofort
  sichtbar (das `task.created`-Event aktualisiert die Aufgabenliste live); einseitige Modulgrenze
  gewahrt; keine Migration; konsistent mit der notes-Konvertierung.
- **Abwägung (E9):** **nur Betreff → Task-Titel** in S5 (kein Body-Übertrag — `tasks` hat dafür über
  `create_personal_task` keine Spalte); Zuweisung an den **Auslöser** (nicht an einen wählbaren
  Verantwortlichen — kein Mitglieder-Picker). Reicherer Übertrag + Verantwortlichen-Wahl + persistenter
  Brief↔Task-`object_link` sind Folge-Slices.
- **Grenzen:** kein gespeicherter Brief↔Task-Link (die Aufgabe „weiß" nicht, dass sie aus einem Brief
  kam) — wie bei den anderen `create_personal_task`-Konvertierungen; der Link kommt mit `object_links`.

## Alternativen
- **Brief beim Konvertieren archivieren/löschen:** verworfen — überraschend und datenverlust-nah;
  non-destruktiv ist sicherer.
- **Aufgabe an den Absender statt den Empfänger:** verworfen — „**Kümmerst du dich?**" heißt: der
  Empfänger nimmt es an; die Zuweisung an den Auslöser (= Empfänger, der konvertiert) trifft das.
- **Rein eventgetrieben** (`letter.*`-Handler): verworfen — die Konvertierung ist eine explizite
  Nutzeraktion; synchron ist atomar + sofort sichtbar.
