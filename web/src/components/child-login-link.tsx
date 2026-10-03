import { Trans } from "@lingui/react";
import { useState } from "react";

import { Button } from "./button";

/** The child sign-in URL for a household. `/child-login` reads the household from the query
 *  string (routes/child-login.tsx) — kids never type a UUID, so somebody has to hand them this. */
export function childLoginUrl(origin: string, householdId: string): string {
  return `${origin}/child-login?household=${encodeURIComponent(householdId)}`;
}

// Shown to admins next to the child-account form: the link a child signs in through, with a copy
// button. Until this existed the page told children to "use the link from your parent" while the
// parent's UI showed neither the link nor the household id.
export function ChildLoginLink({ householdId }: { householdId: string }) {
  const [copied, setCopied] = useState(false);
  const url = childLoginUrl(window.location.origin, householdId);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // No clipboard permission (or an insecure origin): the link is on screen and selectable.
      setCopied(false);
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">
        <Trans id="child.loginLink.label" />
      </p>
      <p className="text-sm text-stein-text">
        <Trans id="child.loginLink.hint" />
      </p>
      <code className="block break-all rounded bg-stein/10 px-1.5 py-0.5 font-mono text-sm">
        {url}
      </code>
      <Button type="button" variant="secondary" onClick={() => void copy()}>
        <Trans id="child.loginLink.copy" />
      </Button>
      {copied ? (
        <p role="status" className="text-sm text-laurus dark:text-laurus-dark">
          <Trans id="child.loginLink.copied" />
        </p>
      ) : null}
    </div>
  );
}
