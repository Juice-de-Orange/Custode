import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  GeocodeResult,
  LocationIn,
  LocationResponse,
  WeatherResponse,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

async function fetchWeather(): Promise<WeatherResponse> {
  const { data, error, response } = await client.get({ url: "/v1/weather" });
  if (error) throw toProblem(error, response?.status);
  return data as WeatherResponse;
}

async function putLocation(body: LocationIn): Promise<LocationResponse> {
  const { data, error, response } = await client.put({ url: "/v1/weather/location", body });
  if (error) throw toProblem(error, response?.status);
  return data as LocationResponse;
}

async function deleteLocation(): Promise<void> {
  const { error, response } = await client.delete({ url: "/v1/weather/location" });
  if (error) throw toProblem(error, response?.status);
}

async function geocode(q: string): Promise<GeocodeResult[]> {
  const { data, error, response } = await client.get({ url: "/v1/weather/geocode", query: { q } });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as GeocodeResult[];
}

export function useGeocode() {
  return useMutation({ mutationFn: geocode });
}

export const WEATHER_QUERY_KEY = ["weather"] as const;

export function useWeather(enabled: boolean) {
  return useQuery({ queryKey: WEATHER_QUERY_KEY, queryFn: fetchWeather, enabled });
}

export function useSetLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: putLocation,
    onSuccess: () => qc.invalidateQueries({ queryKey: WEATHER_QUERY_KEY }),
  });
}

export function useClearLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteLocation,
    onSuccess: () => qc.invalidateQueries({ queryKey: WEATHER_QUERY_KEY }),
  });
}
