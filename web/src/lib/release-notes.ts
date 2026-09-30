// „Was ist neu" — kuratierte, versionierte Release-Notes (KONZEPT §5.12). Bewusst leise: eine
// kleine, statische Liste, gepflegt bei nennenswerten Auslieferungen. Texte über i18n-Schlüssel
// (DE/EN), damit nichts hartkodiert in der UI landet. Datum als ISO-String (stabil sortierbar).
export type ReleaseNote = {
  version: string;
  date: string; // ISO yyyy-mm-dd
  items: string[]; // i18n message keys
};

// Neueste zuerst.
export const RELEASE_NOTES: ReleaseNote[] = [
  {
    version: "0.8",
    date: "2026-06-30",
    items: ["releases.0_8.today", "releases.0_8.digest", "releases.0_8.feedback", "releases.0_8.trash"],
  },
  {
    version: "0.7",
    date: "2026-06-20",
    items: ["releases.0_7.vault", "releases.0_7.letters", "releases.0_7.guides", "releases.0_7.notes"],
  },
];
