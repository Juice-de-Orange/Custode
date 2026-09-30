import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  Snowflake,
  Sun,
  type LucideIcon,
} from "lucide-react";

// Map a WMO weather code (Open-Meteo `weather_code`) to a small condition bucket we have i18n for.
// Pure + exhaustive fallback (unknown -> "cloudy") so the UI never shows a blank condition.
export type WeatherCondition =
  | "clear"
  | "cloudy"
  | "fog"
  | "drizzle"
  | "rain"
  | "snow"
  | "thunder";

export function wmoCondition(code: number): WeatherCondition {
  if (code === 0) return "clear";
  if (code === 1 || code === 2 || code === 3) return "cloudy";
  if (code === 45 || code === 48) return "fog";
  if (code >= 51 && code <= 57) return "drizzle";
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return "rain";
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return "snow";
  if (code >= 95) return "thunder";
  return "cloudy";
}

// A consistent lucide icon per condition (ADR-0075: designed icon set, not per-OS emoji). The
// component is rendered by the caller (e.g. <Icon className=… aria-hidden />).
const ICONS: Record<WeatherCondition, LucideIcon> = {
  clear: Sun,
  cloudy: Cloud,
  fog: CloudFog,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  snow: Snowflake,
  thunder: CloudLightning,
};

export function wmoIcon(code: number): LucideIcon {
  return ICONS[wmoCondition(code)];
}
