import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "../components/button";
import { Field } from "../components/field";
import { i18n } from "../i18n";
import { useClearLocation, useGeocode, useSetLocation, useWeather } from "./queries";
import { wmoIcon } from "./wmo";

// Renders the lucide glyph for a WMO code (decorative; the temperature/label carry the meaning).
function WeatherGlyph({ code, className }: { code: number; className?: string }) {
  const Icon = wmoIcon(code);
  return <Icon className={className} aria-hidden="true" />;
}

// Weather card (KONZEPT §5.14): shows the household forecast when a location is set, otherwise a
// setup prompt for admins. Graceful: an empty forecast (null provider / upstream down) just shows a
// hint, never an error. Only rendered when the `weather` flag is on (see CalendarPage).
export function WeatherCard({ isAdmin }: { isAdmin: boolean }) {
  const weather = useWeather(true);
  const setLocation = useSetLocation();
  const clearLocation = useClearLocation();
  const geo = useGeocode();
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [label, setLabel] = useState("");
  const [placeQuery, setPlaceQuery] = useState("");

  const runSearch = (e: FormEvent) => {
    e.preventDefault();
    if (placeQuery.trim()) geo.mutate(placeQuery.trim());
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const latN = Number(lat);
    const lonN = Number(lon);
    if (!Number.isFinite(latN) || !Number.isFinite(lonN)) return;
    // Round to 2 decimals (~1 km) — coarse on purpose (KONZEPT: no precise tracking).
    setLocation.mutate({
      lat: Math.round(latN * 100) / 100,
      lon: Math.round(lonN * 100) / 100,
      label: label.trim() || null,
    });
  };

  return (
    <section
      aria-labelledby="weather-heading"
      className="rounded-card border border-stein/15 bg-papier p-4 shadow-soft dark:border-stein/15 dark:bg-nacht-2"
    >
      <h2 id="weather-heading" className="font-display text-lg font-semibold tracking-tight">
        <Trans id="weather.section" />
      </h2>

      {weather.isLoading ? (
        <p className="mt-2 text-sm text-stein-text">…</p>
      ) : weather.data?.configured && weather.data.forecast?.current ? (
        <div className="mt-2 space-y-2">
          <p className="flex items-center gap-2 text-tinte dark:text-kalk">
            <WeatherGlyph
              code={weather.data.forecast.current.weather_code}
              className="size-6 text-laurus dark:text-laurus-dark"
            />
            <span>{Math.round(weather.data.forecast.current.temperature_c)}°C</span>
            {weather.data.location?.label ? (
              <span className="text-sm text-stein-text">{weather.data.location.label}</span>
            ) : null}
          </p>
          <ul className="flex flex-wrap gap-3 text-sm text-stein-text">
            {weather.data.forecast.daily.map((d) => (
              <li
                key={d.date}
                className="flex items-center gap-1 rounded-md bg-stein/10 px-2 py-1 dark:bg-kalk/10"
              >
                <WeatherGlyph code={d.weather_code} className="size-4 text-laurus dark:text-laurus-dark" />
                {Math.round(d.temp_min_c)}°–{Math.round(d.temp_max_c)}°
                {typeof d.precipitation_probability_max === "number" &&
                d.precipitation_probability_max >= 50 ? (
                  <span className="ml-1 text-laurus dark:text-laurus-dark">
                    {i18n._("weather.rainHint", { p: d.precipitation_probability_max })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          {isAdmin ? (
            <button
              type="button"
              onClick={() => clearLocation.mutate()}
              className="text-sm text-bernstein-text hover:underline dark:text-bernstein"
            >
              <Trans id="weather.clear" />
            </button>
          ) : null}
        </div>
      ) : weather.data?.configured ? (
        // Location set but no forecast (provider disabled / upstream down) — graceful base path.
        <p className="mt-2 text-sm text-stein-text">
          <Trans id="weather.unavailable" />
        </p>
      ) : isAdmin ? (
        <div className="mt-2 space-y-3">
          {/* Place-name search (P5-S14): pick a place, no raw coordinates needed. */}
          <form onSubmit={runSearch} className="flex flex-wrap items-end gap-2">
            <Field
              id="w-place"
              label={<Trans id="weather.place" />}
              value={placeQuery}
              onChange={(e) => setPlaceQuery(e.target.value)}
              className="min-w-48"
            />
            <Button type="submit" disabled={geo.isPending || !placeQuery.trim()}>
              <Trans id="weather.search" />
            </Button>
          </form>
          {geo.data && geo.data.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {geo.data.map((place, i) => (
                <li key={`${place.name}-${i}`}>
                  <button
                    type="button"
                    onClick={() => {
                      setLat(String(place.lat));
                      setLon(String(place.lon));
                      setLabel(place.name);
                    }}
                    className="rounded-md border border-stein/40 bg-papier px-2 py-1 text-sm text-tinte hover:border-laurus dark:border-stein/25 dark:bg-nacht-2 dark:text-kalk"
                  >
                    {place.name}
                    {place.admin1 ? `, ${place.admin1}` : ""}
                    {place.country ? ` (${place.country})` : ""}
                  </button>
                </li>
              ))}
            </ul>
          ) : geo.data ? (
            <p className="text-sm text-stein-text">
              <Trans id="weather.noPlaces" />
            </p>
          ) : null}
          <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
            <Field
              id="w-lat"
              label={<Trans id="weather.lat" />}
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            className="w-28"
          />
          <Field
            id="w-lon"
            label={<Trans id="weather.lon" />}
            value={lon}
            onChange={(e) => setLon(e.target.value)}
            className="w-28"
          />
          <Field
            id="w-label"
            label={<Trans id="weather.label" />}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-36"
          />
            <Button type="submit" disabled={setLocation.isPending}>
              <Trans id="weather.save" />
            </Button>
          </form>
        </div>
      ) : (
        <p className="mt-2 text-sm text-stein-text">
          <Trans id="weather.notSet" />
        </p>
      )}
    </section>
  );
}
