# ADR-0082: ICS-Feed DST-korrekt — `DTSTART;TZID=` + gesampelte `VTIMEZONE`-Übergänge

- **Status:** beschlossen
- **Datum:** 2026-07-30
- **Betrifft:** `modules/calendar` (`ics.py`, `vtimezone.py`) · **Bezug:** ADR-0042 (Secret-Feed),
  ADR-0047 (tzid-Verankerung), KONZEPT §8.6

## Kontext

ADR-0047 hat Serien an eine echte `tzid` gebunden und die **serverseitige** Expansion damit
DST-korrekt gemacht — und den **Feed** ausdrücklich als Folge-Slice offengelassen: er emittierte
weiterhin `DTSTART` in UTC + `RRULE`. Ein abonnierender Client expandiert das in UTC und sieht
deshalb genau den Drift, den ADR-0047 intern beseitigt hat: die wöchentliche 18:00-Serie steht dem
Nextcloud-/Google-Abonnenten nach der Zeitumstellung auf 17:00.

Dieser ADR löst den offenen Punkt ein und hält die drei Entscheidungen fest, die dabei zu treffen
waren. Sie sind begründungspflichtig, weil zwei davon **Annahmen über die Zukunft** enthalten und
die dritte eine Alternative verwirft, die auf den ersten Blick deutlich billiger aussieht.

## Entscheidung

1. **Events mit echter `tzid` gehen als Ortszeit mit `DTSTART;TZID=` raus**, begleitet von *einer*
   `VTIMEZONE`-Komponente je tatsächlich genutzter Zone, platziert vor den `VEVENT`s (RFC 5545
   §3.6.5). Events mit `tzid="UTC"` bleiben **byte-gleich** — Bestandsabos verschieben sich nicht,
   die Änderung ist für sie ein No-Op.

2. **Explizite `RDATE`-Übergänge, aus `zoneinfo` gesampelt — keine geratene `RRULE`.** Der
   naheliegende Kurzweg ist `RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU`. Er stimmt für EU-Zonen
   *meistens*. Wo er nicht stimmt — historische Sonderfälle, Zonen außerhalb der EU-Regel, künftige
   Gesetzesänderungen —, verschiebt er Termine **jahrelang still** um eine Stunde. Eine falsche
   Regel ist schlechter als kein Feature: sie sieht korrekt aus. Stattdessen sampeln wir die
   tz-Datenbank tageweise, verdichten jeden gefundenen Wechsel per Binärsuche auf die Sekunde und
   schreiben ihn als `RDATE`. Was `zoneinfo` weiß, bekommt der Abonnent; was es nicht weiß,
   erfinden wir nicht.

3. **Der Onset steht in Ortszeit im ALTEN Offset** (`TZOFFSETFROM`, RFC 5545 §3.6.5). Wiens
   Frühjahrswechsel 2026 ist `20260329T020000` (02:00 CET), **nicht** `T030000`. Beim Bau zunächst
   falsch gemacht und korrigiert — der Fehler ist unauffällig, weil er nur am Umstellungstag selbst
   um genau eine Stunde danebenliegt.

4. **Begrenztes, rollendes Fenster:** ein Jahr zurück, fünf Jahre voraus (`YEARS_BACK`,
   `YEARS_FORWARD` in `vtimezone.py`). Ein vollständiger Übergangs-Katalog würde den Feed
   aufblähen, ohne jemandem zu nützen: Abonnenten holen den Feed periodisch neu, das Fenster wandert
   also mit. Die Grenze ist real und benannt — ein Client, der **fünf Jahre lang nicht** neu holt,
   fällt hinter das Fenster; ihm fehlt dann die Übergangsdefinition, nicht der Termin.

Nebenbefund, beim Bau mitgefunden und mitkorrigiert: **ganztägige Events gehen jetzt als
`VALUE=DATE` mit exklusivem `DTEND`**, vorher fälschlich als Mitternachts-Zeitpunkt. Das ist für
Bestandsabos eine sichtbare Verhaltensänderung — und die richtige Richtung: ein Ganztags-Termin ist
kein Zeitpunkt, und als Zeitpunkt wandert er beim Abonnenten mit dessen Zone.

## Konsequenzen

- **Positiv:** der Feed ist DST-korrekt; die Zeitzonen-Wahrheit stammt aus der tz-Datenbank statt
  aus einer Heuristik; UTC-Bestandsabos sind unberührt; die Ausgabe ist eine reine Funktion
  (`render_vtimezone(tzid, now=...)`) und damit ohne Docker testbar.
- **Kosten:** pro Feed-Abruf ein Sampling-Lauf je genutzter Zone. Bei Tagesschritten über sechs
  Jahre sind das ~2.200 `utcoffset()`-Aufrufe je Zone — vernachlässigbar gegenüber der DB-Abfrage,
  und die Zonenzahl je Haushalt ist einstellig.
- **Grenze:** siehe Fenster oben. Sie ist bewusst gewählt, nicht übersehen.
- **Beweis:** `backend/tests/test_calendar_ics_tz.py`. Der Kerntest vergleicht **keine Strings**,
  sondern expandiert die emittierte Serie in der emittierten Zone und prüft die **Wanduhrzeit** über
  beide Umstellungen. Ein String-Vergleich hätte den Onset-Fehler aus Punkt 3 nicht gefunden.

## Alternativen (verworfen)

- **`RRULE` statt `RDATE`** — siehe Entscheidung 2. Billiger und kleiner, aber rät.
- **Fertige Bibliothek für VTIMEZONE-Blöcke** (`icalendar`, `vobject`) — eine neue Abhängigkeit für
  ~150 Zeilen reine Funktion; CLAUDE.md verlangt für neue Technologie ein „Bestehendes scheitert
  nachweislich an X". `zoneinfo` ist Standardbibliothek und *ist* die Quelle, die eine solche Lib
  intern ebenfalls abfragt.
- **Alles weiterhin in UTC ausliefern** — der Status quo aus ADR-0047, hier abgelöst. Der Drift ist
  für den Abonnenten nicht erkennbar und deshalb besonders teuer.
- **Zonen pro Haushalt statt pro Event bündeln** — verworfen aus demselben Grund wie in ADR-0047:
  die Zone gehört zum Event, nicht zum Haushalt.
