import { client } from "../api/client.gen";

// Read a cookie value by name (the CSRF cookie is non-httpOnly by design).
function readCookie(name: string): string | null {
  for (const part of document.cookie.split("; ")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq) === name) {
      return decodeURIComponent(part.slice(eq + 1));
    }
  }
  return null;
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

// A 401 from one of these is meaningful on its own (bad credentials / expired refresh /
// failed ceremony) — refreshing would not help and could loop, so we never intercept them.
//
// Matched by path SEGMENT, not by substring. `path.includes("/login")` also matched the
// *authenticated* route `/v1/auth/login-events`, whose 401 therefore never healed: the security
// activity on /security went silently blank after fifteen minutes.
const NO_REFRESH_PATHS = [
  "/v1/auth/login",
  "/v1/auth/child-login", // unauthenticated PIN ceremony — a 401 means the PIN was wrong
  "/v1/auth/register",
  "/v1/auth/refresh",
  "/v1/auth/logout",
  "/v1/auth/password/forgot",
  "/v1/auth/password/reset",
  "/v1/auth/passkeys/login", // unauthenticated ceremony — a 401 means it failed, not a lapsed session
];

function isBootstrapPath(path: string): boolean {
  return NO_REFRESH_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

// A request body can be read once. `fetch` consumes it, so by the time the response interceptor
// sees the 401 the original is spent and `request.clone()` throws — which is why the silent
// replay only ever worked for GET, and every POST/PATCH/DELETE with a body failed visibly once
// after a pause. The one moment the body is still intact is the REQUEST interceptor, before
// `fetch` runs: clone there and keep the copy keyed by the request the response interceptor will
// be handed. A WeakMap so an un-replayed copy is collected with its request.
const replayable = new WeakMap<Request, Request>();

function rememberForReplay(request: Request): void {
  if (SAFE_METHODS.has(request.method.toUpperCase())) return; // no body to lose
  try {
    replayable.set(request, request.clone());
  } catch {
    // A body that cannot be cloned (e.g. an already-consumed stream) simply is not replayable;
    // the 401 then surfaces as before. Never make the request itself fail over this.
  }
}

// The CSRF cookie is `__Host-custode_csrf` in prod (Secure) and `custode_csrf` in dev.
function csrfToken(): string | null {
  return readCookie("__Host-custode_csrf") ?? readCookie("custode_csrf");
}

function applyCsrf(headers: Headers, method: string): void {
  if (SAFE_METHODS.has(method.toUpperCase())) return;
  const token = csrfToken();
  if (token) headers.set("X-CSRF-Token", token);
  // Drop any inherited header when the cookie is unreadable, so a replayed request never
  // carries a stale (rotated) token.
  else headers.delete("X-CSRF-Token");
}

// Rotate the session via the opaque refresh cookie. Uses a raw fetch (not the generated
// client) so it can never re-enter the response interceptor below and loop.
async function postRefresh(): Promise<boolean> {
  const headers = new Headers();
  const token = csrfToken();
  if (token) headers.set("X-CSRF-Token", token); // /refresh is CSRF-protected
  try {
    const res = await fetch("/v1/auth/refresh", { method: "POST", credentials: "include", headers });
    return res.ok;
  } catch {
    return false; // network error -> treat as not refreshed
  }
}

// Single-flight: when the access token lapses, many in-flight requests 401 at once, but
// only one refresh should run — the rest await the same attempt.
let refreshInFlight: Promise<boolean> | null = null;

function ensureRefreshed(refresh: () => Promise<boolean> = postRefresh): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = refresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/**
 * Rotate the session once, sharing an in-flight attempt with the fetch interceptor.
 *
 * Exported for the SSE channel: `EventSource` is not `fetch`, so a 401 on `/v1/stream` never
 * reaches the response interceptor below — the live channel has to renew for itself.
 */
export function renewSession(): Promise<boolean> {
  return ensureRefreshed();
}

type ResponseDeps = {
  refresh: () => Promise<boolean>;
  replay: (request: Request) => Promise<Response>;
  /** The pristine copy taken before `fetch` consumed the body, if one was kept. */
  buffered?: (request: Request) => Request | undefined;
};

// Decide what to do with a response. On a 401 from an authenticated route, refresh the
// rotating session once and replay the original request — so a lapsed 15-minute access
// token does not look like a logout. Defensive throughout: any failure falls back to the
// original 401, so this can never make a request fail worse than it already did.
export async function handleResponse(
  response: Response,
  request: Request,
  deps: ResponseDeps,
): Promise<Response> {
  if (response.status !== 401) return response;

  let path: string;
  try {
    path = new URL(request.url).pathname;
  } catch {
    return response;
  }
  if (isBootstrapPath(path)) return response;

  let refreshed = false;
  try {
    refreshed = await deps.refresh();
  } catch {
    return response;
  }
  if (!refreshed) return response; // refresh expired -> genuine unauth

  try {
    // The buffered copy for anything with a body; a fresh clone for GET, where the original is
    // still intact. Falls back to the clone when nothing was buffered (tests, safe methods).
    const retry = deps.buffered?.(request) ?? request.clone();
    applyCsrf(retry.headers, retry.method); // the CSRF cookie rotated on refresh
    return await deps.replay(retry);
  } catch {
    return response;
  }
}

// Configure the generated client for our cookie sessions: send cookies on every request,
// echo the double-submit CSRF token on unsafe methods, and silently refresh on 401.
export function configureAuthClient(): void {
  client.setConfig({ credentials: "include" });
  client.interceptors.request.use((request) => {
    applyCsrf(request.headers, request.method);
    // Must happen here and nowhere else: this is the last moment the body is unread.
    rememberForReplay(request);
    return request;
  });
  client.interceptors.response.use((response, request) =>
    handleResponse(response, request, {
      refresh: () => ensureRefreshed(),
      replay: (req) => fetch(req),
      buffered: (req) => {
        const copy = replayable.get(req);
        replayable.delete(req); // one replay per request; a second attempt is a genuine 401
        return copy;
      },
    }),
  );
}
