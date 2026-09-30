import { Trans } from "@lingui/react";
import { useRegisterSW } from "virtual:pwa-register/react";

import { Button } from "./button";

// PWA update flow (ADR-0078): registerType "prompt" — the freshly installed service worker
// WAITS until the user opts in, so a running session (half-filled form, cook mode) is never
// reloaded from under them. Split like CommandDialog/CommandPalette: the presentational half
// renders without the build-time virtual module, so vitest/axe can test it directly.

export function UpdateToast({
  onReload,
  onDismiss,
}: {
  onReload: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-above-bar z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-card border border-stein/15 bg-papier px-4 py-3 shadow-elev dark:border-stein/20 dark:bg-nacht-2 md:inset-x-auto md:bottom-6 md:right-6"
    >
      <span className="text-sm">
        <Trans id="pwa.update.available" />
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          <Trans id="pwa.update.dismiss" />
        </Button>
        <Button size="sm" onClick={onReload}>
          <Trans id="pwa.update.reload" />
        </Button>
      </div>
    </div>
  );
}

// Browsers re-check the SW only on navigation, but an installed app can stay open for weeks:
// poll hourly and when the user returns to the app. Module-level once-guard (onRegisteredSW can
// re-fire on a StrictMode dev remount) + throttle — visibility flips are frequent on phones and
// every update() refetches sw.js over the network.
let updateLoopStarted = false;
const UPDATE_CHECK_MIN_MS = 15 * 60 * 1000;

function startUpdateLoop(registration: ServiceWorkerRegistration): void {
  if (updateLoopStarted) return;
  updateLoopStarted = true;
  let lastCheck = Date.now(); // the registration itself was the first check
  const check = () => {
    if (Date.now() - lastCheck < UPDATE_CHECK_MIN_MS) return;
    lastCheck = Date.now();
    void registration.update().catch(() => undefined); // offline: retry on the next tick
  };
  setInterval(check, 60 * 60 * 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check();
  });
}

export function PwaUpdateToast() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (registration) startUpdateLoop(registration);
    },
  });
  if (!needRefresh) return null;
  return (
    <UpdateToast
      onReload={() => void updateServiceWorker(true)}
      onDismiss={() => setNeedRefresh(false)}
    />
  );
}
