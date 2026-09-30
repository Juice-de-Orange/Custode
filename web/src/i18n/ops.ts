// Katalog der **Betreiber-Konsole**: `ops.*` plus die Handvoll Schlüssel, die geteilte
// Komponenten mitbringen (`locales/shared.*`). Ausdrücklich NICHT `./index` — das lüde den
// kompletten Mitglieder-Katalog in ein Bundle, das ihn nie anzeigt.
//
// Nur zwei Dateien dürfen das hier importieren: `ops/main.tsx` und `ops/routes/feedback.tsx`.
// Alle anderen Ops-Bausteine beziehen ihre Übersetzung über `useLingui()` aus dem Provider und
// wissen deshalb gar nicht, welcher Katalog aktiv ist — genau so soll es bleiben.

import { messages as de } from "./locales/ops.de";
import { messages as en } from "./locales/ops.en";
import { activateCatalogs } from "./core";

export const i18n = activateCatalogs(de, en);
