# Modul `weather`

**Status:** in Arbeit · **Phase:** 5 · **KONZEPT:** §5.14

## Zweck & Verantwortung
Grober Haushalts-Standort + Wetter-Vorhersage (Open-Meteo) mit vollwertigem Basis-Pfad ohne Provider
(Null-Adapter). Eigenständiger Wert (Regen-Hinweis, Synergie S-15) und späterer Eingang der
Scheduling-Engine. Importiert **nur** `kernel/*`; kein Modul liest seine Tabelle.

## Datenobjekte (Migration 0038)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `weather_locations` | id; `lat` (CHECK −90..90); `lon` (CHECK −180..180); `label?`; ein Eintrag pro Haushalt (Upsert); bewusst **grob** (UI rundet auf 2 Dezimalen — kein Präzisions-Tracking) | `household_id = app.household_id` (USING + WITH CHECK) |

RLS-Negativtest (`test_weather_rls.py`: A↛B→0, WITH CHECK).

## Graceful Enhancement (ADR-0045)
Zwei Provider hinter `WeatherProvider` (`fetch(lat, lon) -> Forecast | None`): `OpenMeteoProvider`
(öffentliche Open-Meteo-API) und `NullWeatherProvider` (immer `None` = Basis-Pfad). Die Wahl trifft das
Betreiber-Setting `weather_provider` (`open-meteo` | `null`). **Jeder** Upstream-Fehler (HTTP/JSON) →
`None` → leere Vorhersage, **nie** 5xx. `forecast.py::parse_open_meteo` ist rein (ohne DB/Netz/Docker
testbar) und tolerant gegen fehlende Felder. Die Vorhersage wird in Redis unter einem groben Key
(`weather:{lat.2f}:{lon.2f}`, TTL `weather_cache_ttl_s`, Default 1 h) gecacht.

## Sicherheit
Open-Meteo-Host ist **fix verdrahtet**, nur bounds-geprüfte numerische lat/lon variieren → **keine
SSRF-Fläche** (anders als der Rezept-Import mit nutzergegebenen URLs, `kernel/fetch.py`). lat/lon grob
gespeichert; keine PII in Logs/Cache-Keys. Ein Webcal-/CalDAV-Abo mit URLs (späterer Slice) würde
`kernel/fetch.safe_fetch` nutzen.

## Schnittstellen
- **HTTP `/v1/weather` (member/admin):** `GET` → `WeatherResponse {configured, location?, forecast?}`
  (leer = Basis-Pfad: kein Standort / Null-Provider / Upstream aus).
- **HTTP `/v1/weather/geocode?q=` (member/admin):** Ortsnamen-Suche → `list[GeocodeResult {name, lat,
  lon, country?, admin1?}]` (Open-Meteo-Geocoding, fixer Host → keine SSRF; Redis-Cache 1 Tag; leer bei
  Wetter aus / Upstream weg). Das Web wählt einen Treffer und setzt damit den Standort (P5-S14).
- **HTTP `/v1/weather/location` (admin, CSRF):** `PUT {lat, lon, label?}` (Upsert) · `DELETE` (entfernt).
- **Cross-Modul:** importiert **nur** `kernel/*`. `weather.api` exportiert `get_forecast(session)`;
  `scheduling` liest die Vorhersage **einseitig** darüber (P5-S8c, Regen-Hinweis) — nie die Tabelle.
- **Events out:** — (keine).

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member | admin | fremder Haushalt |
|---|---|---|---|---|---|
| `GET /weather` | ✗ (401) | ✗ (403) | ✓ | ✓ | RLS: nur eigener Standort |
| `PUT/DELETE /weather/location` | ✗ | ✗ (403) | ✗ (403) | ✓ | **RLS** |

## Flags
Das per-Haushalt-Flag `weather` (Default **aus**, `kernel/config/flags.py` + `web/src/lib/flags.ts`)
blendet das Web-Widget ein/aus. Server-seitig ist Wetter über den Null-Adapter abschaltbar; eine
server-seitige Flag-Erzwingung würde `accounts` brauchen und ist bewusst nicht in diesem Slice (S7).

## Tests
- `test_weather_forecast.py` — **reine** Parser-/Null-Adapter-Unit-Tests (beide Pfade, ohne Docker).
- `test_weather_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_weather_http.py` — Standort-CRUD (admin-only, 403 für member), Forecast über injizierten
  Provider (Happy-Path + Cache), Null-Provider → leere Vorhersage, ungültige Koordinaten → 422.
- `web/src/test/wmo.test.ts` — WMO-Code → Condition-Bucket (+ Fallback nie leer).

## Offene Punkte (spätere Slices)
- **`weather.api`-Naht** für die Scheduling-Engine (✅ P5-S8c), stündliche Werte/Wetter-Alerts,
  ggf. Wetter→Mealplan (additiv). (Geocoding: **✅ P5-S14**.)
