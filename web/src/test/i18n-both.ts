// Test-Hilfe: **beide** Kataloge in derselben Lingui-Instanz.
//
// Nur für Tests, die absichtlich über die Grenze hinweg rendern — `a11y.test.tsx` prüft
// Bausteine aus der Mitglieder-App und aus der Betreiber-Konsole in einem Lauf. Im echten Build
// gibt es diese Vereinigung nicht: jeder Entry lädt genau seinen Katalog, und dass er das tut,
// prüft `i18n-bundle-split.test.ts`.
//
// Ein Test, der nur eine Oberfläche rendert, nimmt `../i18n` bzw. `../i18n/ops` — sonst verdeckt
// er genau den Fehler, den die Trennung sichtbar machen soll.

import { messages as de } from "../i18n/locales/de";
import { messages as en } from "../i18n/locales/en";
import { messages as opsDe } from "../i18n/locales/ops.de";
import { messages as opsEn } from "../i18n/locales/ops.en";
import { activateCatalogs } from "../i18n/core";

export const i18n = activateCatalogs({ ...de, ...opsDe }, { ...en, ...opsEn });
