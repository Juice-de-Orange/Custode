// Schlüssel, die BEIDE Oberflächen brauchen — Mitglieder-App und Betreiber-Konsole.
// Sie stammen aus geteilten Komponenten (Lade-/Fehlerzustand, Theme-Umschalter,
// Dashboard-Kachel, Passkey-Verwaltung), nicht aus einer geteilten Fachlichkeit.
// Wer hier etwas hinzufügt, lädt es in beide Bundles — im Zweifel gehört es woanders hin.

export const shared: Record<string, string> = {
  "today.empty": "Noch nichts für heute geplant.",
  "today.viewAll": "alle ansehen",
  "state.loading": "Lädt …",
  "state.error": "Etwas ist schiefgelaufen.",
  "security.passkeys.empty": "Noch keine Passkeys hinterlegt.",
  "security.passkeys.nameLabel": "Name des Geräts",
  "security.passkeys.add": "Passkey hinzufügen",
  "security.passkeys.delete": "Entfernen",
  "security.passkeys.confirmDelete": "Diesen Passkey wirklich entfernen?",
  "security.passkeys.unsupported": "Dieser Browser unterstützt keine Passkeys.",
  "security.passkeys.created": "Erstellt am",
  "theme.toggle": "Design: {mode}",
};
