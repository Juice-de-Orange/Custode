import { Trans } from "@lingui/react";

import { RELEASE_NOTES } from "../lib/release-notes";

// „Was ist neu" — leise Release-Notes-Ansicht (KONZEPT §5.12). Öffentlich/leichtgewichtig:
// keine Daten-Fetches, kein Login nötig — eine ruhige Liste der letzten Verbesserungen.
export function ReleasesPage() {
  return (
    <section aria-labelledby="releases-heading" className="space-y-6">
      <h1 id="releases-heading" className="font-display text-2xl">
        <Trans id="releases.title" />
      </h1>
      <ol className="space-y-6">
        {RELEASE_NOTES.map((r) => (
          <li key={r.version} className="space-y-2">
            <h2 className="flex items-baseline gap-2 font-display text-lg">
              <span>{r.version}</span>
              <span className="font-mono text-sm text-stein-text">{r.date}</span>
            </h2>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {r.items.map((key) => (
                <li key={key}>
                  <Trans id={key} />
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}
