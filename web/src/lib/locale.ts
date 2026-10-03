// Interface language. Two catalogs ship (German, English); which one is active is decided once at
// load: an explicit choice stored in this browser wins, otherwise the browser's language list,
// otherwise German (the language the product is designed in). The choice is per browser, like the
// theme — it is a display preference, not account data.
export type Locale = "de" | "en";

export const LOCALES: readonly Locale[] = ["de", "en"];

const KEY = "custode-locale";

function asLocale(value: string | null | undefined): Locale | null {
  return value === "de" || value === "en" ? value : null;
}

/** The explicit choice stored in this browser, or `null` for "follow the browser". */
export function getLocalePref(): Locale | null {
  try {
    return asLocale(localStorage.getItem(KEY));
  } catch {
    return null; // localStorage unavailable — fall through to the browser language
  }
}

/** Store (or, with `null`, forget) the explicit choice. Takes effect on the next load. */
export function setLocalePref(locale: Locale | null): void {
  try {
    if (locale === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, locale);
  } catch {
    /* best effort */
  }
}

/** Pure decision: stored choice, else the first browser language we have a catalog for, else de. */
export function resolveLocale(stored: string | null, browser: readonly string[]): Locale {
  const explicit = asLocale(stored);
  if (explicit) return explicit;
  for (const tag of browser) {
    const base = asLocale(tag.toLowerCase().split("-")[0]);
    if (base) return base;
  }
  return "de";
}

function browserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  if (navigator.languages?.length) return navigator.languages;
  return navigator.language ? [navigator.language] : [];
}

export function detectLocale(): Locale {
  return resolveLocale(getLocalePref(), browserLanguages());
}
