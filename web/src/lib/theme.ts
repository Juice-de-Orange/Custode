// Dark-mode preference (ADR-0075). Three states: follow the OS ("system", the default) or force
// "light"/"dark". The `.dark` class on <html> drives Tailwind's class-based dark variant; an inline
// script in index.html applies it pre-paint (no flash). All screens are dark-ready (Slice 4d), so
// the toggle is safe to expose.
export type ThemePref = "light" | "dark" | "system";

const KEY = "custode-theme";

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* localStorage unavailable — fall through to the default */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

function resolveDark(pref: ThemePref): boolean {
  return pref === "dark" || (pref === "system" && systemPrefersDark());
}

// Mirrors --color-kalk / --color-nacht (and the two media-gated metas in index.html).
const THEME_COLORS = { light: "#fafaf7", dark: "#141513" } as const;

// The media-gated <meta name="theme-color"> tags only follow the OS scheme. When the user
// FORCES light/dark against the OS, the standalone title-/status-bar tint (PWA, ADR-0078)
// would stay wrong — so both metas are rewritten to the forced color, and restored on "system".
function syncThemeColorMeta(pref: ThemePref, dark: boolean): void {
  const metas = document.head.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"][media]');
  metas.forEach((meta) => {
    if (pref === "system") {
      meta.content = meta.media.includes("dark") ? THEME_COLORS.dark : THEME_COLORS.light;
    } else {
      meta.content = dark ? THEME_COLORS.dark : THEME_COLORS.light;
    }
  });
}

export function applyThemePref(pref: ThemePref): void {
  const dark = resolveDark(pref);
  document.documentElement.classList.toggle("dark", dark);
  syncThemeColorMeta(pref, dark);
}

export function setThemePref(pref: ThemePref): void {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* best effort */
  }
  applyThemePref(pref);
}

// Keep a "system" preference reactive to OS theme changes while the app is open.
export function initThemeWatch(): void {
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (getThemePref() === "system") applyThemePref("system");
    });
  } catch {
    /* no matchMedia — nothing to watch */
  }
}
