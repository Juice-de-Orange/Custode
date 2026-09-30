import { useLingui } from "@lingui/react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";

import { getThemePref, setThemePref, type ThemePref } from "../lib/theme";

const ORDER: ThemePref[] = ["system", "light", "dark"];
const ICONS = { system: Monitor, light: Sun, dark: Moon } as const;

// Cycles system → light → dark. The current mode's icon is shown; the accessible name announces it.
export function ThemeToggle() {
  const { i18n } = useLingui();
  const [pref, setPref] = useState<ThemePref>(() => getThemePref());
  const Icon = ICONS[pref];
  const cycle = () => {
    const next = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
    setThemePref(next);
    setPref(next);
  };
  const label = i18n._("theme.toggle", { mode: i18n._(`theme.${pref}`) });
  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={label}
      title={label}
      className="rounded-md p-2 text-tinte transition-colors hover:bg-stein/10 dark:text-kalk dark:hover:bg-kalk/10"
    >
      <Icon className="size-5" aria-hidden="true" />
    </button>
  );
}
