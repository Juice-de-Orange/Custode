import { Trans } from "@lingui/react";
import { Share } from "lucide-react";
import { useState } from "react";

import { useInstallPrompt } from "../lib/useInstallPrompt";
import { Button } from "./button";

// Install affordance (ARCHITECTURE §5 / ADR-0078: "dezenter Install-Hinweis, kein Nag").
// Presentational card + two wired variants: a permanent section on /profile and a quiet,
// forever-dismissible hint on /today after repeated visits. The card renders without any
// browser install API, so vitest/axe can drive every state.

export function InstallCard({
  variant,
  onInstall,
  onDismiss,
}: {
  variant: "prompt" | "ios";
  onInstall?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div className="rounded-card border border-stein/15 bg-papier p-4 shadow-soft dark:border-stein/20 dark:bg-nacht-2">
      <h2 className="font-display text-base font-semibold">
        <Trans id="install.title" />
      </h2>
      <p className="mt-1 text-sm text-stein-text">
        <Trans id="install.body" />
      </p>
      {variant === "ios" ? (
        <>
          <p className="mt-2 flex items-start gap-2 text-sm">
            <Share className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>
              <Trans id="install.ios.hint" />
            </span>
          </p>
          <p className="mt-1 text-sm text-stein-text">
            <Trans id="install.ios.note" />
          </p>
        </>
      ) : null}
      {variant === "prompt" || onDismiss ? (
        <div className="mt-3 flex items-center gap-2">
          {variant === "prompt" ? (
            <Button size="sm" onClick={onInstall}>
              <Trans id="install.cta" />
            </Button>
          ) : null}
          {onDismiss ? (
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              <Trans id="install.dismiss" />
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Permanent, quiet placement in the profile settings.
export function InstallAppSection() {
  const { canInstall, isIos, isStandalone, promptInstall } = useInstallPrompt();
  if (isStandalone || (!canInstall && !isIos)) return null;
  return (
    <InstallCard
      variant={canInstall ? "prompt" : "ios"}
      onInstall={() => void promptInstall()}
    />
  );
}

const VISITS_KEY = "custode-install-visits";
const DISMISS_KEY = "custode-install-hint-dismissed";

// /today hint: appears from the third visit on, disappears forever on dismiss ("kein Nag").
export function InstallHintCard() {
  const { canInstall, isIos, isStandalone, promptInstall } = useInstallPrompt();
  const [initial] = useState(() => {
    try {
      const dismissed = localStorage.getItem(DISMISS_KEY) !== null;
      const visits = Number(localStorage.getItem(VISITS_KEY) ?? 0) + 1;
      localStorage.setItem(VISITS_KEY, String(visits));
      return { dismissed, visits };
    } catch {
      return { dismissed: true, visits: 0 }; // no storage → no way to stay quiet → never nag
    }
  });
  const [hidden, setHidden] = useState(false);
  if (
    hidden ||
    initial.dismissed ||
    initial.visits < 3 ||
    isStandalone ||
    (!canInstall && !isIos)
  ) {
    return null;
  }
  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* best effort */
    }
    setHidden(true);
  };
  return (
    <InstallCard
      variant={canInstall ? "prompt" : "ios"}
      onInstall={() => void promptInstall()}
      onDismiss={dismiss}
    />
  );
}
