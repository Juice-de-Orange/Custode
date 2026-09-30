# ADR-0030: SSRF-Guard für ausgehende URL-Abrufe (`kernel/fetch.py`)

- **Status:** beschlossen
- **Datum:** 2026-06-19
- **Betrifft:** `kernel/fetch.py`, `modules/recipes` (Import) · **Bezug:** KONZEPT §8, ARCHITECTURE §16

## Kontext

Der Rezept-Import ruft eine **vom Nutzer angegebene URL serverseitig ab** — laut KONZEPT §8 „die
exponierteste Stelle des Backends". Ohne Schutz ist das eine klassische **SSRF**-Lücke: ein Angreifer
lässt den Server interne Dienste, private Ranges (RFC1918), `localhost` oder den Cloud-Metadata-Endpunkt
`169.254.169.254` abrufen — direkt oder via DNS (ein öffentlicher Name, der auf eine interne IP zeigt)
oder via Redirect. Mehrere künftige Funktionen (Wetter, CalDAV) holen ebenfalls fremde URLs.

## Entscheidung

Ein **zentrales Kernel-Utility `kernel/fetch.py::safe_fetch(url)`** ist der einzige erlaubte Weg, eine
nutzerangegebene URL abzurufen:

- **Schema-Whitelist:** nur `http`/`https` (kein `file://`, `gopher://`, …).
- **DNS-Auflösung + Range-Validierung:** der Host wird aufgelöst und **jede** zurückgegebene A/AAAA-
  Adresse muss öffentlich-routbar sein — `private`/`loopback`/`link-local`/`multicast`/`reserved`/
  `unspecified` werden geblockt (via `ipaddress`). Das blockt „Name → interne IP" (DNS-Pinning-Intent:
  wir vertrauen den aufgelösten Adressen, nicht dem Namen).
- **Redirects manuell + gekappt:** `follow_redirects=False`, Schleife mit Cap **≤ 3**, **Ziel jeder
  Weiterleitung wird erneut validiert** (Redirect → intern ist blockiert).
- **Limits:** Timeout (10 s, Connect 5 s); Response **gestreamt** und bei **2 MiB** abgebrochen.
- **Opake Fehler:** alle Ablehnungen liefern denselben generischen `import_url_blocked` (nie die
  aufgelöste IP oder welche Prüfung griff) — kein Informationsleck.

Das HTML wird so sicher geholt; die Extraktion (JSON-LD, später `recipe-scrapers`) bekommt nur den
fertigen Text und geht **nie selbst** ins Netz.

## Konsequenzen

- **Positiv:** alle praktischen SSRF-Vektoren (literale interne IPs, DNS→intern, Redirect→intern,
  Metadata-Endpunkt, Nicht-HTTP-Schemata, Riesen-Responses) sind geblockt; ein einziger, getesteter
  Guard, wiederverwendbar für Wetter/CalDAV. Unit-Tests laufen **ohne Docker/Netz** (IP-Klassifikation,
  Schema, gemockte DNS).
- **Restpunkt (dokumentiert):** ein **Sub-TTL-DNS-Rebind** zwischen unserer `getaddrinfo`-Auflösung und
  httpx' eigener Auflösung beim Connect ist nicht geschlossen. **Connection-level IP-Pinning** (Connect
  auf die validierte IP, Host/SNI erhalten) ist ein **Härtungs-Follow-up**. Wir validieren jeden
  aufgelösten Record, was die realen Vektoren abdeckt; der Rebind erfordert einen Angreifer mit
  kontrollierter Sub-Sekunden-TTL.

## Alternativen (verworfen)

- **httpx `follow_redirects=True`** — bequem, aber verliert die Pro-Hop-Re-Validierung (Redirect→intern
  bliebe offen). Verworfen.
- **`recipe-scrapers` selbst fetchen lassen** — würde den Guard umgehen (die Lib zieht die URL selbst).
  Stattdessen: **wir** fetchen via `safe_fetch`, die Lib bekommt nur das HTML (`scrape_html`, S3b).
- **Allowlist bekannter Rezept-Domains** — zu eng (Nutzer importieren beliebige Seiten); pflegeintensiv.
  Verworfen.

## Nachtrag P9 (2026-07-30) — Credential-Formen und Origin-Lock

Der Guard hat seit Phase 9 ein Geschwister: **`safe_request`** (gleiche Engine, zusätzlich Methode,
Body und Credentials) für CalDAV-Server, deren URL ebenfalls vom Nutzer stammt. Damit wandern zum
ersten Mal **Zugangsdaten** durch diesen Pfad, und daraus folgt eine Invariante, die vorher nicht
formuliert werden musste:

1. **Jede** Credential-Form sperrt Redirects auf die Ursprungs-Origin — Basic-Tupel **wie**
   Bearer-Token. Der Lock hing anfangs an `auth is not None` allein; ein Bearer wäre einem fremden
   Redirect ungeschützt gefolgt (negativprobiert, s. `docs/BUGLOG.md` 2026-07-30). Bei einem Bearer
   wiegt das schwerer als bei Basic: er ist reines Inhaberrecht **ohne jede eigene Origin-Bindung**.
2. **Auflage:** eine Credential gehört immer an `auth=` bzw. `bearer=` — **nie** von Hand in
   `headers`. Dort sieht der Guard sie nicht und der Origin-Lock greift nicht. Das gilt für jeden
   künftigen Aufrufer (Google-CalDAV, weitere Provider).
3. Die Lehre dahinter ist übertragbar: ein Sicherheits-Gate, das an einer konkreten
   Credential-**Repräsentation** hängt statt am Begriff „Credential", fällt beim nächsten
   Auth-Verfahren still auf.

Vorgänger: ADR-0079 §7 (dort erstmals formuliert, damals noch Basic-only). Beleg:
`backend/tests/test_fetch_ssrf.py`.
