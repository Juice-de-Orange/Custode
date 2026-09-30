# ADR-0045 — Wetter: Provider-Adapter mit Null-Adapter, eigenes Standort-Modell, Open-Meteo fix

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S7
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Phase 5 braucht ein **Wetter-Signal** (KONZEPT §5.14) — eigenständig nützlich (Regen-Hinweis) und
später Eingang der Scheduling-Engine. Root-CLAUDE macht drei harte Vorgaben: **Graceful Enhancement**
(„jede Funktion hat einen vollwertigen Basis-Pfad ohne sie (Null-Adapter); Tests decken beide Pfade
ab"), **Modulgrenzen** (Module importieren nur `kernel/*`; kein Modul liest fremde Tabellen) und
**SSRF-Schutz** bei ausgehenden Calls.

## Entscheidung
1. **Provider-Adapter hinter einem Protocol.** `weather/provider.py` definiert `WeatherProvider`
   (`fetch(lat, lon) -> Forecast | None`) mit zwei Implementierungen: `OpenMeteoProvider` (ruft die
   öffentliche Open-Meteo-API) und `NullWeatherProvider` (liefert immer `None` = Basis-Pfad). Die Wahl
   trifft die **betreiberseitige** Einstellung `weather_provider` (`open-meteo` | `null`). **Jeder**
   Ausfall (HTTP-Fehler, kaputtes JSON) führt zu `None` → die App degradiert auf eine **leere**
   Vorhersage, nie auf 5xx. Beide Pfade sind getestet (`test_weather_forecast` + `test_weather_http`).
2. **Reiner Parser.** `weather/forecast.py::parse_open_meteo` ist DB-/netzfrei und ohne Docker
   testbar (Kalender-Muster). Tolerant gegen fehlende/kurze Arrays (lieber weniger Tage als ein 500).
3. **Eigenes Standort-Modell statt Fremd-Tabelle.** Der grobe Haushalts-Standort lebt in der
   **modul-eigenen** Tabelle `weather_locations` (Migration 0038, RLS `household_isolation` + FORCE +
   Negativtest), **nicht** in `households.settings_json` (das gehört `accounts`). So importiert
   `weather` ausschließlich `kernel/*` — keine Modulgrenz-Verletzung, ein neuer import-linter-Contract
   („weather must not depend on other modules"). Ein Eintrag pro Haushalt (Upsert); lat/lon werden
   bewusst **grob** gespeichert (UI rundet auf 2 Nachkommastellen ~1 km — kein Präzisions-Tracking).
4. **Open-Meteo = fixer Host → keine SSRF-Fläche.** Anders als der Rezept-Import (nutzergegebene URLs,
   `kernel/fetch.py`) ist der Host hier **fest verdrahtet**; nur die bounds-geprüften, numerischen
   lat/lon variieren. Darum genügt ein direkter, getimeouteter `httpx`-GET; kein URL-Guard nötig.
5. **Caching in Redis.** Die Vorhersage wird unter einem **groben** Key (`weather:{lat.2f}:{lon.2f}`)
   für `weather_cache_ttl_s` (Default 1 h) gecacht — schont Open-Meteos Fair-Use und teilt Treffer
   benachbarter Haushalte. Keine PII im Key (grobe Koordinaten).
6. **Flag-Gate UI-seitig.** Das per-Haushalt-Flag `weather` (Default aus) blendet das Widget im Web
   ein/aus (`flags.ts`). Server-seitig ist Wetter unkritisch (nicht-sensibel) und über den Null-Adapter
   ohnehin abschaltbar; eine server-seitige Flag-Erzwingung wäre nur über `accounts` erreichbar und
   wird bewusst **nicht** in diesem Slice eingeführt (kein Cross-Modul-Read für ein UI-Gate).

## Konsequenzen
- **Positiv:** voll funktionsfähig ohne Provider (Null-Adapter); saubere Modulgrenze (nur kernel);
  keine SSRF-Fläche; additive Migration mit RLS-Negativtest; reiner Parser → schnelle Tests; Caching
  begrenzt Upstream-Last.
- **Abwägung:** Standort doppelt gedacht (nicht in `households.settings_json`) — bewusst, um die
  Modulgrenze sauber zu halten. Server-seitiges Flag-Gate verschoben (UI-Gate genügt für ein
  optionales, nicht-sensibles Feature).
- **Grenzen / später:** Geocoding (Ortsname → lat/lon) — vorerst gibt der Nutzer Koordinaten ein;
  Wetter→Scheduling-Naht (`weather.api`) kommt mit der Scheduling-Engine; stündliche Werte/Alerts offen.

## Alternativen
- **Standort in `households.settings_json`:** verworfen — erzwingt einen `weather→accounts`-Cross-Read
  oder einen neuen kernel-Pfad; die eigene Tabelle ist grenz-sauber und RLS-testbar.
- **`kernel/fetch.safe_fetch` für Open-Meteo:** unnötig — der Host ist fix; SSRF-Guard ist für
  nutzergegebene URLs da. (Für ein späteres Webcal-/CalDAV-Abo mit URLs ist `safe_fetch` der Weg.)
- **Kein Caching:** verworfen — verletzt Open-Meteos Fair-Use bei mehreren Haushalten.
