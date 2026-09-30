// Export problem slugs -> catalog message refs, mirroring wearables/errors.ts and
// calendar/errors.ts. Clients branch on the stable ``slug``, never on the server's message text.

import { ProblemError } from "../lib/problem";

export type MessageRef = { id: string; reference?: string };

const SLUG_MESSAGES: Record<string, string> = {
  // 413 from kernel/http/export.py: the archive exceeded the direct-download cap. Not the
  // member's fault and not retryable by them — it is an operator handover.
  export_too_large: "export.err.tooLarge",
  // 403 from require_role(admin) on the household route. Only reachable if the role changed
  // between render and click, so it must read as information, not as an accusation.
  forbidden: "export.err.forbidden",
  // The auth interceptor already tried a silent refresh; a surviving 401 is a real logout.
  http_401: "export.err.session",
};

export function exportProblemMessage(error: unknown): MessageRef {
  const problem = error instanceof ProblemError ? error : null;
  return {
    id: (problem && SLUG_MESSAGES[problem.slug]) || "export.err.generic",
    // The reference code is the only thing support can correlate without asking for content.
    reference: problem?.reference,
  };
}
