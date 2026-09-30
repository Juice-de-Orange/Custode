// Wearable problem slugs + callback error codes -> catalog message refs (P9-S8), mirroring
// calendar/errors.ts. One central map instead of scattered slug comparisons.

import { ProblemError } from "../lib/problem";

export type MessageRef = { id: string };

const SLUG_MESSAGES: Record<string, string> = {
  feature_disabled: "wearables.err.featureDisabled",
  wearables_disabled: "wearables.err.providerOff",
  crypto_unconfigured: "wearables.err.cryptoOff",
  connection_exists: "wearables.err.exists",
  not_found: "wearables.err.notFound",
  forbidden: "wearables.err.forbidden",
};

/** The ``?error=`` codes the unauthenticated callback redirects with (backend router._back). */
const CALLBACK_MESSAGES: Record<string, string> = {
  denied: "wearables.cb.denied",
  state_invalid: "wearables.cb.stateInvalid",
  exchange_failed: "wearables.cb.exchangeFailed",
  forbidden: "wearables.cb.forbidden",
  crypto_unconfigured: "wearables.err.cryptoOff",
};

export function wearableProblemMessage(error: unknown): MessageRef {
  const slug = error instanceof ProblemError ? error.slug : undefined;
  return { id: (slug && SLUG_MESSAGES[slug]) || "wearables.err.generic" };
}

export function callbackMessage(code: string): MessageRef {
  return { id: CALLBACK_MESSAGES[code] ?? "wearables.cb.failed" };
}

/** ``last_error`` on a connection -> catalog id. Only ``needs_reauth`` is actionable for the
 *  member; everything else is an operational hiccup the next nightly run may fix by itself. */
export function connectionStatusId(status: string, lastError: string | null | undefined): string {
  if (status === "needs_reauth") return "wearables.status.needsReauth";
  if (lastError) return "wearables.status.problem";
  return "wearables.status.ok";
}
