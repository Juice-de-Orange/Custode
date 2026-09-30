# CLAUDE.md — Modul `weather`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Grober Haushalts-Standort + Wetter-Vorhersage (KONZEPT §5.14, Open-Meteo). Eigenständiger Wert
(Regen-Hinweis) und späterer Eingang der Scheduling-Engine. P5-S7.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „weather must not depend on
  other modules"). Standort liegt in der **eigenen** Tabelle `weather_locations` (RLS, Negativtest) —
  **nicht** in `households.settings_json` (das gehört `accounts`; Cross-Read wäre Grenz-Bruch).

## Graceful Enhancement (ADR-0045, harte Root-Regel)
- Zwei Provider hinter `WeatherProvider`: `OpenMeteoProvider` + `NullWeatherProvider`. Wahl über
  Betreiber-Setting `weather_provider`. **Jeder** Upstream-Fehler → `None` → leere Vorhersage, **nie**
  5xx. **Beide Pfade getestet** (`test_weather_forecast` + `test_weather_http`).
- `forecast.py::parse_open_meteo` ist **rein** (ohne DB/Netz, ohne Docker testbar). **Nie** den Parser
  an DB/Netz koppeln. Tolerant gegen fehlende Felder (lieber weniger Tage als ein 500).

## Sicherheit
- Open-Meteo-Host ist **fix verdrahtet**; nur bounds-geprüfte numerische lat/lon variieren → **keine
  SSRF-Fläche** (kein URL-Guard nötig). **Nie** eine nutzergegebene URL serverseitig abrufen — dafür
  wäre `kernel/fetch.safe_fetch` da (späteres Webcal/CalDAV-Abo).
- lat/lon werden **grob** gespeichert (UI rundet auf 2 Dezimalen); Cache-Key ist grob → keine PII.

## Schnittstellen (HTTP, `/v1/weather`)
- `GET /v1/weather` (member/admin) → `WeatherResponse {configured, location?, forecast?}` (leer = Basis).
- `GET /v1/weather/geocode?q=` (member/admin) → Ortsnamen-Suche (Open-Meteo-Geocoding, fixer Host →
  keine SSRF; Redis-Cache 1 Tag; leer/graceful). **Nie** eine nutzergegebene URL abrufen.
- `PUT /v1/weather/location` (**admin**, CSRF) → setzt/aktualisiert den Standort (Upsert).
- `DELETE /v1/weather/location` (**admin**, CSRF) → entfernt ihn (zurück auf Basis-Pfad).

## Cross-Modul
- `weather.api` exportiert `get_forecast(session)` — `scheduling` liest die Vorhersage **einseitig**
  darüber (P5-S8c). Kein Modul liest die `weather`-Tabelle oder den Provider direkt.

## Events
- **publiziert:** — (keine; Standort-Änderung ist still). **abonniert:** —.

## No-Gos
- **Kein** Cross-Modul-Import (nur kernel). **Kein** Fremd-Tabellen-Lesen.
- **Kein** 5xx bei Wetter-Ausfall — immer leere Vorhersage (Basis-Pfad).
- **Keine** nutzergegebene Fetch-URL (SSRF). **Keine** präzisen Koordinaten/PII in Logs/Cache-Keys.
