// Membership problem slugs -> catalog message refs, mirroring export/errors.ts. Clients branch on
// the stable ``slug``, never on the server's message text.
//
// The three refusals of an exit are the point of this table. They look alike and mean different
// things, and the difference decides what the person can do next:
//
//   last_admin     — somebody else *can* take over. Fixable right here, on this screen.
//   only_children  — nobody can. Der Weg ist die Auflösung, und die gibt es seit 11-S1e.
//   sole_member    — there is nobody at all. Ebenfalls Auflösung, aber ein anderer Satz: die
//                    Person steckt nicht fest, sie hat nur nach dem Falschen gefragt.
//
// Seit ADR-0085 zeigen `sole_member` und `only_children` auf eine Schaltfläche, die es gibt. Die
// Slugs bleiben (der Server unterscheidet die Fälle weiterhin), die Texte nicht mehr auf ein
// „noch nicht".
//   child_cannot_leave — a child account has no way back in (no e-mail, no password). The UI
//                    hides the button, so this only surfaces in a race; it still needs a sentence.
//
// Collapsing them into one "you cannot leave" would tell someone to transfer a role to a person
// who does not exist.

import { ProblemError } from "../lib/problem";

export type MessageRef = { id: string; reference?: string };

const SLUG_MESSAGES: Record<string, string> = {
  last_admin: "members.err.lastAdmin",
  only_children: "members.err.onlyChildren",
  sole_member: "members.err.soleMember",
  child_cannot_leave: "members.err.childCannotLeave",
  // 403 from require_role(admin) — reachable if the caller's own role changed between render and
  // click. Reads as information, not as an accusation.
  forbidden: "members.err.forbidden",
  not_found: "members.err.gone",
  already_dissolved: "members.err.alreadyDissolved",
  name_mismatch: "members.err.nameMismatch",
  http_401: "members.err.session",
};

export function memberProblemMessage(error: unknown): MessageRef {
  const problem = error instanceof ProblemError ? error : null;
  return {
    id: (problem && SLUG_MESSAGES[problem.slug]) || "state.error",
    reference: problem?.reference,
  };
}
