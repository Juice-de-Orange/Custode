import { useEffect, useState } from "react";

// Public demo mode (docs/demo.md). The server says whether this instance is a demo: `/v1/demo`
// (not in the OpenAPI schema, like /healthz) answers `{enabled: false}` on a normal instance, and
// everything here stays inert. A 404 (an older server) means the same. The demo login is public by
// design — the sign-in page shows it.

export type DemoInfo = {
  enabled: boolean;
  email: string;
  password: string;
  reset_interval_minutes: number;
  resetting: boolean;
};

export async function fetchDemo(): Promise<DemoInfo | null> {
  try {
    const response = await fetch("/v1/demo", { credentials: "same-origin" });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<DemoInfo>;
    return body.enabled === true ? (body as DemoInfo) : null;
  } catch {
    return null; // no demo endpoint, offline, or a test environment — not a demo
  }
}

// One request per page load, shared by every caller. Deliberately not a TanStack query: the
// banner and the sign-in page must not depend on a QueryClient being mounted around them.
let pending: Promise<DemoInfo | null> | null = null;
let known: DemoInfo | null | undefined;

function loadDemo(): Promise<DemoInfo | null> {
  pending ??= fetchDemo().then((info) => (known = info));
  return pending;
}

/** Forget the answer (tests only — a page load asks once). */
export function resetDemoCache(): void {
  pending = null;
  known = undefined;
}

/** `null` on a normal instance, the demo's login and state on a demo. */
export function useDemo(): DemoInfo | null {
  const [info, setInfo] = useState<DemoInfo | null>(known ?? null);
  useEffect(() => {
    let live = true;
    void loadDemo().then((value) => {
      if (live) setInfo(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return info;
}

// The server refuses some actions in the demo (`demo_disabled`). Forms show their own generic
// error; the banner adds the reason. A tiny event channel keeps `query.ts` free of React.
const listeners = new Set<() => void>();

export function notifyDemoDisabled(): void {
  for (const listener of listeners) listener();
}

export function onDemoDisabled(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
