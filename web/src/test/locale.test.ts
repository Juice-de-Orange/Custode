import { i18n } from "@lingui/core";
import { afterEach, describe, expect, test } from "vitest";

import { activateCatalogs } from "../i18n/core";
import { messages as de } from "../i18n/locales/de";
import { messages as en } from "../i18n/locales/en";
import { detectLocale, getLocalePref, resolveLocale, setLocalePref } from "../lib/locale";

// The README says the UI ships in German and English. Until 2026-10-03 the English catalog was
// loaded and never activated (`i18n.activate("de")`, no switch) — complete, tested for parity,
// and unreachable. These pin the decision and that the catalog loader actually follows it.

afterEach(() => {
  setLocalePref(null);
  activateCatalogs(de, en); // back to the suite's German browser (test/setup.ts)
});

describe("resolveLocale", () => {
  test("a stored choice wins over the browser", () => {
    expect(resolveLocale("en", ["de-DE", "de"])).toBe("en");
    expect(resolveLocale("de", ["en-US"])).toBe("de");
  });

  test("without a choice the first browser language with a catalog decides", () => {
    expect(resolveLocale(null, ["en-GB", "de"])).toBe("en");
    expect(resolveLocale(null, ["de-AT", "en"])).toBe("de");
    expect(resolveLocale(null, ["fr-FR", "en-US", "de"])).toBe("en");
  });

  test("falls back to German — for no match, no list, and a stored value that is not a locale", () => {
    expect(resolveLocale(null, ["fr-FR", "it"])).toBe("de");
    expect(resolveLocale(null, [])).toBe("de");
    expect(resolveLocale("klingon", ["en-US"])).toBe("en"); // garbage is ignored, not obeyed
  });
});

describe("stored choice", () => {
  test("round-trips through localStorage and can be forgotten", () => {
    expect(getLocalePref()).toBeNull();
    setLocalePref("en");
    expect(getLocalePref()).toBe("en");
    expect(detectLocale()).toBe("en");
    setLocalePref(null);
    expect(getLocalePref()).toBeNull();
    expect(detectLocale()).toBe("de"); // the suite's browser is German
  });
});

describe("activateCatalogs", () => {
  test("activates German for a German browser", () => {
    activateCatalogs(de, en);
    expect(i18n.locale).toBe("de");
    expect(i18n._("vault.unlock")).toBe("Entsperren");
    expect(document.documentElement.lang).toBe("de");
  });

  test("activates English when English is chosen — the catalog is reachable", () => {
    setLocalePref("en");
    activateCatalogs(de, en);
    expect(i18n.locale).toBe("en");
    expect(i18n._("vault.unlock")).toBe("Unlock");
    expect(document.documentElement.lang).toBe("en");
  });
});
