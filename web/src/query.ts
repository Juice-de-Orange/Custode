import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { recordDiagnostic } from "./lib/diagnostics";
import { ProblemError } from "./lib/problem";

// Record a technical breadcrumb for every failed query/mutation: the route + the error-reference
// short-code (no content/PII). Feeds the opt-in feedback diagnostics attachment (KONZEPT §5.12).
function recordError(error: unknown): void {
  const ref = error instanceof ProblemError ? error.reference : undefined;
  const slug = error instanceof ProblemError ? error.slug : undefined;
  recordDiagnostic({
    route: typeof window !== "undefined" ? window.location.pathname : null,
    error_ref: ref ?? slug ?? null,
  });
}

// Server-state lives in Query (ARCHITECTURE §5). SSE invalidation-hints invalidate query keys
// precisely (src/realtime); refetch-on-focus (TanStack default) is the fallback when the
// stream is unavailable.
export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: recordError }),
  mutationCache: new MutationCache({ onError: recordError }),
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
});
