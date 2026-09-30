import { Trans } from "@lingui/react";

import { useOnline } from "../lib/useOnline";

// Quiet global connectivity hint (UX_KONZEPT §2: "Sync-/Offline-Indikator: leise, nie Modal").
// Mobile: a small pill above the bottom bar, left of the palette FAB; desktop: bottom-right.
export function OfflineDot() {
  const online = useOnline();
  if (online) return null;
  return (
    <div
      role="status"
      className="fixed bottom-above-bar left-4 z-40 w-fit max-w-[70vw] truncate rounded-pill border border-bernstein/40 bg-bernstein/15 px-3 py-1 text-xs text-bernstein-text backdrop-blur dark:bg-bernstein/20 dark:text-bernstein md:bottom-4 md:left-auto md:right-4"
    >
      <Trans id="app.offline" />
    </div>
  );
}
