import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { renewSession } from "../auth/client";
import { useSession } from "../auth/session";
import { queryKeysForEntity, sideEffectForEntity } from "./invalidation-map";
import { openInvalidationStream } from "./stream";

// Opens the SSE invalidation stream while the user is signed in and invalidates the mapped
// query keys on each hint; closes on sign-out / unmount. Failure is silent — the app stays
// usable via refetch-on-focus (graceful enhancement).
export function useRealtime(): void {
  const qc = useQueryClient();
  const { data: session } = useSession();
  const signedIn = Boolean(session);
  useEffect(() => {
    if (!signedIn) return;
    const stream = openInvalidationStream(
      (hint) => {
        const invalidate = () => {
          for (const queryKey of queryKeysForEntity(hint.entity)) {
            void qc.invalidateQueries({ queryKey });
          }
        };
        const effect = sideEffectForEntity(hint.entity);
        if (effect) void effect().then(invalidate, invalidate);
        else invalidate();
      },
      // Ohne das bleibt der Live-Kanal nach dem ersten 401 dauerhaft stumm: der Browser gibt bei
      // einer Nicht-2xx-Antwort endgültig auf, und EventSource läuft nicht durch den
      // fetch-Interceptor.
      { renew: renewSession },
    );
    return () => stream.close();
  }, [signedIn, qc]);
}
