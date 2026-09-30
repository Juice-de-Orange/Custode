// Live invalidation over SSE (ARCHITECTURE §7, ADR-002). The browser EventSource connects to
// the same-origin /v1/stream (cookies ride along), receives `event: invalidate` frames, and
// hands each parsed hint to `onHint`. Graceful enhancement: with no EventSource (old browser /
// test env) this is a no-op and the app falls back to refetch-on-focus.
//
// **Why there is a retry loop here after all.** The comment that used to stand in its place said
// "the browser auto-reconnects on drop, so there is no manual retry loop" — true for a dropped
// connection, and false for the case that actually happens: when the server answers non-2xx the
// browser gives up **permanently** (`readyState === CLOSED`, no further attempts). The access
// cookie lapses after fifteen minutes, so `/v1/stream` answers 401 and the live channel goes
// silent for the rest of the session — until some unrelated `fetch` happened to rotate the
// session and the user reloaded. EventSource is not `fetch`, so the 401 interceptor in
// `auth/client.ts` never sees it; renewing has to happen here.

export type InvalidationHint = { entity: string; id: string; version: number };

export type InvalidationStream = { close: () => void };

const NOOP_STREAM: InvalidationStream = { close: () => {} };

// Backoff for permanent closes. Short first (a lapsed cookie is fixed by one rotation), then
// spread out so a server that is genuinely down is not hammered. The last value repeats.
const RETRY_DELAYS_MS = [1_000, 5_000, 15_000, 60_000];

export type StreamOptions = {
  url?: string;
  /** Rotate the session before reconnecting — the usual reason for a permanent close is a
   *  lapsed access cookie. Omitted in tests and on the null path. */
  renew?: () => Promise<boolean>;
  retryDelaysMs?: number[];
};

export function openInvalidationStream(
  onHint: (hint: InvalidationHint) => void,
  options?: StreamOptions,
): InvalidationStream {
  if (typeof EventSource === "undefined") return NOOP_STREAM; // null path — no push, app still works

  const url = options?.url ?? "/v1/stream";
  const delays = options?.retryDelaysMs ?? RETRY_DELAYS_MS;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let disposed = false;

  const connect = (): void => {
    if (disposed) return;
    const current = new EventSource(url, { withCredentials: true });
    source = current;

    current.addEventListener("open", () => {
      attempt = 0; // a live connection resets the backoff, not the passage of time
    });

    current.addEventListener("invalidate", (event) => {
      let hint: InvalidationHint;
      try {
        hint = JSON.parse((event as MessageEvent).data) as InvalidationHint;
      } catch {
        return; // ignore a malformed frame
      }
      if (hint && typeof hint.entity === "string") onHint(hint);
    });

    current.addEventListener("error", () => {
      // A transient drop leaves readyState at CONNECTING and the browser retries by itself —
      // touching it here would fight the browser. Only a CLOSED socket is ours to revive.
      if (disposed || current.readyState !== 2 /* CLOSED */) return;
      const delay = delays[Math.min(attempt, delays.length - 1)];
      attempt += 1;
      timer = setTimeout(() => {
        if (disposed) return;
        const renew = options?.renew;
        if (!renew) {
          connect();
          return;
        }
        // Reconnect regardless of the outcome: a failed rotation may just mean the network is
        // down, and a session that is genuinely over answers 401 again — which lands back here
        // with a longer delay instead of a tight loop.
        void renew().then(connect, connect);
      }, delay);
    });
  };

  connect();

  return {
    close: () => {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      source?.close();
    },
  };
}
