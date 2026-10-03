// Was beide Oberflächen am i18n gemeinsam haben — und nichts von dem, was sie trennt.
//
// Hier steht KEIN Katalog. Das ist der Punkt der Datei: `index.ts` (Mitglieder-App) und `ops.ts`
// (Betreiber-Konsole) laden je ihren eigenen, und weil der Ladevorgang hier liegt statt dort,
// kann keiner von beiden versehentlich den anderen mitziehen.
//
// WICHTIG (BUGLOG, unverändert gültig): Lingui interpoliert in einem Produktions-Build nur
// **kompilierte** Messages. Rohe Katalog-Strings rendern dort mit ihren literalen
// {Platzhaltern} und unaufgelösten ICU-Pluralen. In dev und in Tests kompiliert Lingui zur
// Laufzeit, was den Fehler jahrelang verdecken kann. Deshalb wird jeder Eintrag beim Laden in
// Linguis Token-Form übersetzt — dev und prod verhalten sich dann gleich.

import { i18n } from "@lingui/core";
import { compileMessage } from "@lingui/message-utils/compileMessage";

import { detectLocale } from "../lib/locale";

type Compiled = ReturnType<typeof compileMessage>;

function compileCatalog(msgs: Record<string, string>): Record<string, Compiled> {
  const out: Record<string, Compiled> = {};
  for (const [id, msg] of Object.entries(msgs)) out[id] = compileMessage(msg);
  return out;
}

/** Load one surface's DE+EN catalogs into the shared Lingui instance and activate the language
 *  for this browser (stored choice, else browser language, else German — `lib/locale`).
 *  Called exactly once per entry point, at module load. */
export function activateCatalogs(
  de: Record<string, string>,
  en: Record<string, string>,
): typeof i18n {
  i18n.load({ de: compileCatalog(de), en: compileCatalog(en) });
  const locale = detectLocale();
  i18n.activate(locale);
  // index.html ships lang="de"; screen readers and hyphenation follow this attribute.
  if (typeof document !== "undefined") document.documentElement.lang = locale;
  return i18n;
}
