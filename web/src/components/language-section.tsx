import { Trans, useLingui } from "@lingui/react";
import { useState } from "react";

import { getLocalePref, type Locale, LOCALES, setLocalePref } from "../lib/locale";

// Interface language (lib/locale): follow the browser, or pin German/English for this browser.
// A native <select> — the set is closed and tiny. Changing it reloads the page: many components
// read the catalog at render time without subscribing to a locale change, and a reload is the
// one way to be sure nothing stale stays on screen.
export function LanguageSection({
  onChanged = () => window.location.reload(),
}: {
  onChanged?: () => void;
}) {
  const { i18n } = useLingui();
  const [pref, setPref] = useState<Locale | null>(() => getLocalePref());

  return (
    <section aria-labelledby="language-heading" className="space-y-2">
      <h2 id="language-heading" className="font-display text-lg">
        <Trans id="profile.language.title" />
      </h2>
      <label htmlFor="language-select" className="block text-sm font-medium text-tinte dark:text-kalk">
        <Trans id="profile.language.label" />
      </label>
      <select
        id="language-select"
        value={pref ?? "auto"}
        onChange={(event) => {
          const value = event.target.value;
          const next = LOCALES.find((l) => l === value) ?? null;
          setLocalePref(next);
          setPref(next);
          onChanged();
        }}
        className="block rounded-md border border-stein/40 bg-kalk px-3 py-2 text-tinte focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:bg-nacht-2 dark:text-kalk dark:focus:ring-laurus-dark/40"
      >
        <option value="auto">{i18n._("profile.language.auto")}</option>
        <option value="de">{i18n._("profile.language.de")}</option>
        <option value="en">{i18n._("profile.language.en")}</option>
      </select>
      <p className="text-sm text-stein-text">
        <Trans id="profile.language.hint" />
      </p>
    </section>
  );
}
