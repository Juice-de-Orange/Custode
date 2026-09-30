// Config for `lingui extract` / `lingui compile`. Wired fully in Phase 1 once
// UI strings use the t`` / <Trans> macro. Phase 0 uses runtime catalogs
// (src/i18n/locales/*) so the build needs no extract step yet.
export default {
  locales: ["de", "en"],
  sourceLocale: "de",
  catalogs: [
    {
      path: "<rootDir>/src/i18n/locales/{locale}/messages",
      include: ["src"],
    },
  ],
};
