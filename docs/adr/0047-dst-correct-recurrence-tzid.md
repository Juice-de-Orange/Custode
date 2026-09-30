# ADR-0047 — DST-korrekte Serien: Verankerung in der Event-Zeitzone (`tzid`)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S9
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Bis P5-S8 wurden RRULE-Serien in **UTC** verankert: `starts_at` (ein UTC-Instant) als `dtstart`,
Expansion in UTC. Das ist für „alle 24 h" korrekt, aber **falsch** für menschliche Wiederholungen wie
„jeden Montag 09:00". Über eine Sommer-/Winterzeit-Umstellung wandert ein UTC-fixer Termin in der
Ortszeit um eine Stunde (09:00 → 10:00). Das Phase-5-Ziel verlangt explizit **„DST-Testsuite grün"**.

## Entscheidung
1. **Jedes Event trägt eine IANA-Zeitzone `tzid`** (Spalte `calendar_events.tzid`, Migration 0039,
   Default `'UTC'`, additiv). Eine Serie wird in **dieser** Zone expandiert: `expand.py` setzt
   `dtstart = starts_at.astimezone(ZoneInfo(tzid))`, `dateutil` erzeugt die Occurrences wall-clock-
   stabil, und jede wird per `astimezone(UTC)` als UTC-Instant ausgegeben. So bleibt „Montag 09:00
   Wien" über die Umstellung um 09:00 Ortszeit; nur der UTC-Offset wandert (08:00Z ↔ 07:00Z).
2. **Reine Funktion bleibt rein.** `tzid` ist ein Parameter von `expand_occurrences`/`is_occurrence`
   (Default `"UTC"` → exakt das alte Verhalten). Eine **DST-Testsuite** (`test_calendar_dst.py`,
   ohne Docker) beweist Wall-clock-Stabilität über Frühling/Herbst und zeigt den Kontrast zu
   `tzid="UTC"` (gewollte Drift).
3. **Default = Browser-Zeitzone.** Das Web sendet beim Anlegen
   `Intl.DateTimeFormat().resolvedOptions().timeZone`, sodass Termine ohne Zutun in der lokalen Zone
   verankert sind. Unbekannte/ungültige Zone → 422 (`is_valid_tzid`); bei der Expansion fällt eine
   kaputte Zone defensiv auf UTC zurück (nie ein 5xx).

## Konsequenzen
- **Positiv:** menschliche Serien sind DST-korrekt; additive Migration (Bestandsdaten = `UTC`,
  Verhalten unverändert); reine, schnell testbare Funktion; deckt ein Phase-5-Abnahmekriterium ab.
- **Abwägung / bewusst später** *(überholt — eingelöst, s. Nachtrag unten und ADR-0082)*:
  Der **ICS-Feed** (ADR-0042) emittiert weiterhin `DTSTART` in **UTC**
  + `RRULE`; ein abonnierender Client expandiert in UTC und sieht daher denselben DST-Drift wie vor
  S9. DST-korrektes ICS braucht `DTSTART;TZID=` **plus** einen `VTIMEZONE`-Block — ein eigener,
  größerer Slice. Die **serverseitige** Agenda/Scheduling-Expansion (das, was die DST-Testsuite prüft)
  ist jetzt korrekt; der Feed bleibt als dokumentierter Folge-Slice offen.
- **Grenzen:** all-day-Events nutzen `tzid` nicht relevant (kein Zeitanteil); Dauer wird absolut
  (UTC-`timedelta`) erhalten — gewollt.

## Alternativen
- **Haushalts-Zeitzone statt Event-`tzid`:** verworfen — Mitglieder in verschiedenen Zonen / Reisen;
  die Zone gehört zum Event. (Eine Haushalts-Default-Zone als UI-Vorbelegung ist davon unberührt.)
- **EXDATE/EXDATE-Anker in UTC lassen:** verworfen — die Cancel-Validierung (`is_occurrence`) muss in
  derselben Zone verankern, sonst verfehlt sie DST-verschobene Instanzen.
- **Naive Local-Times speichern:** verworfen — `timestamptz` (UTC-Instant) + `tzid` ist eindeutig und
  RLS-/Vergleichs-freundlich; naive Zeiten wären mehrdeutig.

## Nachtrag P9 (2026-07-30) — der Folge-Slice ist gebaut, revidiert durch ADR-0082

Der oben als offen vermerkte Punkt „ICS-Feed bleibt UTC" gilt **nicht mehr**. Der Feed emittiert
Events mit echter `tzid` als Ortszeit mit `DTSTART;TZID=` plus einer `VTIMEZONE` je genutzter Zone;
UTC-Events bleiben byte-gleich. Die dabei getroffenen Entscheidungen — gesampelte `RDATE`-Übergänge
statt geratener `RRULE`, Onset im alten Offset, begrenztes Fenster, `VALUE=DATE` für Ganztags —
stehen in **[ADR-0082](0082-ics-feed-vtimezone.md)**. Der Abwägungs-Bullet oben bleibt als
historischer Stand stehen (E9: nicht still ändern).
