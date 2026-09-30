# NOTIFICATIONS — Default-Matrix (Platzhalter)

> Phase-1-Deliverable (KONZEPT §5.12). Diese Datei spezifiziert die
> **Default-Matrix** `Ereignistyp × Kanal × Rolle` und muss das **P1-Budget**
> nachweisen: standardmäßig **max. 1 gebündelter Push pro Person und Tag** plus
> direkte, persönlich betreffende Ereignisse. Alles bündel- und abschaltbar.

Kanäle: In-App-Inbox · Web Push (VAPID) · später FCM (Android) · E-Mail-Digest
(täglich/wöchentlich).

## Matrix

| Ereignistyp | Inbox | Web Push | E-Mail-Digest | Default-Rolle(n) | direkt/gebündelt |
|---|---|---|---|---|---|
| `market.listing.sold` (mich betreffend) | ✓ | ✓ | – | member | direkt |
| `letter.received` | ✓ | ✓ | – | alle | direkt |
| **Wochen-Überblick (Aufgaben)** | – | – | **wöchentlich (Mo 07:00)** | admin/member | gebündelt |

### Implementiert: Wochen-Digest (P8-S7, ADR-0070)
- **Kanal:** E-Mail (`MailPort`; Graceful — ohne SMTP via Null-Adapter kein Versand).
- **Auslöser:** Worker-Cron `send_weekly_digest_job` (Mo 07:00), haushaltsübergreifend unter der
  **maint-Rolle** (ARCH §9). Modul `digest` (Logik-only).
- **Empfänger:** erwachsene Mitglieder (`admin`/`member`) **mit** E-Mail. **Kinder/Gäste ausgeschlossen.**
- **Inhalt v1:** offene/überfällige Aufgaben des Haushalts (nur eigene Aggregate, keine PII im Log).
  Mahlzeiten + weitere Module folgen.
- **Opt-out:** je Haushalt über `households.settings_json['digest_enabled']` (Default an). Admin-
  Umschaltung ✅ (P8-S7b: Settings-Endpoint + `DigestToggle` in der Konto-Ansicht).
- **P1-Budget:** ein gebündelter Wochenversand; kein Push, keine Einzel-Events.

_Inbox/Push-Kanäle + volle kanalübergreifende Bündelung wachsen mit den weiteren Slices._

## Was ausdrücklich **keine** Benachrichtigung auslöst

Damit die Lücke nicht wie ein Versehen aussieht und jemand eine Mail nachbaut:

- **Haushalts-Auflösung** (11-S1e) und **Kontolöschung** (11-S1c) — beide gehen von der
  betroffenen Person selbst aus bzw. vom Admin, der sie im selben Bildschirm bestätigt. Eine Mail
  danach informierte niemanden über etwas Neues.
- **Konto-Purge** (03:30) und **Haushalts-Purge** (04:00) — sie laufen 30 Tage später und
  protokollieren nur **Zähler**, nie Inhalte und nie Empfänger. Eine Benachrichtigung „deine Daten
  sind jetzt weg" ginge an eine Adresse, die es nicht mehr geben soll.
- Die **anderen Mitglieder** eines aufgelösten Haushalts erfahren es daran, dass ihr Zugang endet
  (Sitzungen widerrufen, Zugänge entwertet). KONZEPT §5.1 verlangt hier nichts darüber hinaus.
