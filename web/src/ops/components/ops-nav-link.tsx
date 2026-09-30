import type { ReactNode } from "react";

import { opsRouter } from "../router";

// The ops bundle does not register its router type globally (the member router owns that slot
// in the shared tsc project — see router.tsx), so the typed <Link to> isn't available here.
// This nav link drives client-side navigation through the ops router instance instead, keeping
// the in-memory bearer token alive (a full <a> reload would drop it and log the operator out).
export type OpsPath =
  | "/"
  | "/banners"
  | "/flags"
  | "/households"
  | "/feedback"
  | "/operators"
  | "/passkeys"
  | "/audit";

export function OpsNavLink({ to, children }: { to: OpsPath; children: ReactNode }) {
  return (
    <a
      href={to}
      onClick={(e) => {
        // Honour modifier-clicks (open in new tab) by falling through to the default.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        // The global Register slot holds the member router, so navigate() types ``to`` against
        // member paths. ``to`` is already constrained to the ops route tree via OpsPath; this one
        // cast bridges to the (correctly-routed at runtime) ops router instance.
        void opsRouter.navigate({ to: to as never });
      }}
      className="text-sm text-laurus dark:text-laurus-dark hover:underline focus:outline-none focus:ring-2 focus:ring-laurus/40"
    >
      {children}
    </a>
  );
}
