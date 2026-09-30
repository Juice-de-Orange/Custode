import { createClient, createConfig } from "@hey-api/client-fetch";

import type { ClientOptions } from "../api/types.gen";

// Dedicated @hey-api client for the operator console — a separate instance from the member
// client (auth/client.ts). The ops console authenticates with an opaque **bearer token**
// (ADR-0072): no cookie, no CSRF, own subdomain. The token lives only in memory — a reload
// requires a fresh login, so it is never persisted to storage where XSS could lift it.
export const opsClient = createClient(createConfig<ClientOptions>());

let opsToken: string | null = null;

export function setOpsToken(token: string | null): void {
  opsToken = token;
}

export function hasOpsToken(): boolean {
  return opsToken !== null;
}

// Paths whose 401 is meaningful on its own (bad credentials) — clearing the token there is a
// no-op, but we never treat them as a lapsed session.
const NO_CLEAR_PATHS = ["/ops/auth/login"];

// Attach the bearer token to every request; on a 401 from an authenticated route, drop the
// token so the session query (`/ops/me`) flips to unauthenticated and the router redirects to
// the login screen. There is no silent refresh — operator sessions are short-lived by design.
export function configureOpsClient(): void {
  opsClient.interceptors.request.use((request) => {
    if (opsToken) request.headers.set("Authorization", `Bearer ${opsToken}`);
    return request;
  });
  opsClient.interceptors.response.use((response, request) => {
    if (response.status === 401) {
      let path = "";
      try {
        path = new URL(request.url).pathname;
      } catch {
        path = "";
      }
      if (!NO_CLEAR_PATHS.some((p) => path.includes(p))) opsToken = null;
    }
    return response;
  });
}
