// Household feature flags — the SAME defaults + merge as the API (backend kernel/config/flags.py),
// so UI and API decide identically. The API returns the merged result in `/me`.flags; these helpers
// provide a typed default and an explicit merge for parity tests and client-side fallbacks. Keep
// the keys/values in lockstep with the backend.
export const DEFAULT_HOUSEHOLD_FLAGS: Record<string, boolean> = {
  recipes: true,
  mealplanner: true,
  shopping: true,
  calendar: true,
  tasks: true,
  marketplace: true,
  marketplace_children: false, // hard child-safety default
  vault: true,
  messaging: true,
  guides: true,
  notes: true,
  finances: false,
  wearables: false,
  weather: false,
  ai: false,
};

// Merge DEFAULT ← global (operator) ← settings_json (household admin); output keys are exactly the
// default keys, values coerced to boolean. Mirrors get_household_flags() in the backend.
export function getHouseholdFlags(
  settingsJson: Record<string, unknown> | null | undefined,
  globalFlags: Record<string, boolean>,
): Record<string, boolean> {
  const merged: Record<string, boolean> = { ...DEFAULT_HOUSEHOLD_FLAGS };
  for (const source of [globalFlags as Record<string, unknown>, settingsJson ?? {}]) {
    for (const key of Object.keys(DEFAULT_HOUSEHOLD_FLAGS)) {
      if (key in source) merged[key] = Boolean(source[key]);
    }
  }
  return merged;
}

// Read a flag from the API-provided `/me`.flags (already merged), falling back to the static default.
export function flagEnabled(flags: Record<string, boolean> | undefined, key: string): boolean {
  return flags?.[key] ?? DEFAULT_HOUSEHOLD_FLAGS[key] ?? false;
}
