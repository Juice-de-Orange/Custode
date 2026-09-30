// Katalog der **Mitglieder-App**. Die Betreiber-Konsole hat einen eigenen (`./ops`) — wer hier
// importiert, zieht 733 Schlüssel mit, die sie nie braucht.
//
// Der Import-Pfad `../i18n` bleibt für die Mitglieder-App unverändert; die Trennung ist von
// dieser Seite aus unsichtbar.

import { messages as de } from "./locales/de";
import { messages as en } from "./locales/en";
import { activateCatalogs } from "./core";

export const i18n = activateCatalogs(de, en);
