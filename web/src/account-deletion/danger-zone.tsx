// "Konto löschen" (Art. 17). Lives on /profile beside the export, because both are the person's
// own rights rather than household administration.
//
// Three deliberate choices:
//
// 1. **Blockers are asked before the button is offered, not after it is pressed.** The backend
//    answers 409 either way, but a danger zone that invites a click and then explains why it was
//    impossible teaches people that the button lies. `last_admin` is also actionable elsewhere
//    (/account → change a role), so the message points there.
// 2. **Two steps, not window.confirm.** Every other destructive action in the app uses the native
//    dialog, and for a session or a passkey that is proportionate. This one removes the person
//    from every household immediately and cannot be taken back; the second step is in the page,
//    reads what actually happens, and survives a screen reader.
// 3. **The consequences are spelled out, including the one that surprises.** Leaving happens at
//    once — the grace period protects the *account*, not the memberships.

import { Trans, useLingui } from "@lingui/react";
import { Loader2 } from "lucide-react";
import { useState } from "react";

import type { DeletionBlockerResponse } from "../api/types.gen";
import { Button } from "../components/button";
import { ErrorState, LoadingState } from "../components/states";
import { ProblemError } from "../lib/problem";
import { useDeleteAccount, useDeletionBlockers } from "./queries";

/** Every reason the server can give, mapped to a sentence. An unknown reason must still say
 *  something true, so the fallback is the generic one rather than an empty line. */
function blockerMessage(reason: string): string {
  return reason === "last_admin"
    ? "deletion.blocker.lastAdmin"
    : reason === "only_children"
      ? "deletion.blocker.onlyChildren"
      : "deletion.blocker.generic";
}

export function DangerZone({ onDeleted }: { onDeleted: () => void }) {
  const { i18n } = useLingui();
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const blockers = useDeletionBlockers(open);
  const remove = useDeleteAccount();

  const list: DeletionBlockerResponse[] = blockers.data ?? [];
  const blocked = list.length > 0;

  return (
    <section aria-labelledby="danger-heading" className="space-y-3 border-t border-rost/30 pt-6">
      <h2 id="danger-heading" className="font-display text-lg text-rost">
        <Trans id="deletion.title" />
      </h2>
      <p className="text-sm text-stein-text">
        <Trans id="deletion.intro" />
      </p>

      {!open ? (
        <Button type="button" variant="secondary" size="sm" onClick={() => setOpen(true)}>
          <Trans id="deletion.open" />
        </Button>
      ) : blockers.isError ? (
        <ErrorState />
      ) : /* `!isSuccess`, not `isLoading`. In react-query v5 `isLoading = isPending && isFetching`,
            and a query that cannot fetch (offline: fetchStatus "paused") is neither — so
            `isLoading` is false while `data` is still undefined, `list` falls back to `[]`, and the
            delete button would appear WITHOUT the blockers ever having been asked. This is a PWA;
            offline is a reachable state, not a corner case. Serving a stale cached answer on a
            second open has the same shape. */
      !blockers.isSuccess ? (
        <LoadingState />
      ) : blocked ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">
            <Trans id="deletion.blocked" />
          </p>
          <ul className="space-y-1 text-sm">
            {list.map((blocker) => (
              <li key={blocker.household_id}>
                <span className="font-medium">{blocker.name}</span>{" "}
                <Trans id={blockerMessage(blocker.reason)} />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-3">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>
              <Trans id="deletion.consequence.households" />
            </li>
            <li>
              <Trans id="deletion.consequence.economy" />
            </li>
            <li>
              <Trans id="deletion.consequence.grace" />
            </li>
            <li>
              <Trans id="deletion.consequence.final" />
            </li>
          </ul>

          {!armed ? (
            <Button type="button" variant="danger" size="sm" onClick={() => setArmed(true)}>
              <Trans id="deletion.start" />
            </Button>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="danger"
                size="sm"
                disabled={remove.isPending}
                onClick={() => {
                  setFailure(null);
                  remove.mutate(undefined, {
                    onSuccess: onDeleted,
                    onError: (err) =>
                      setFailure(
                        err instanceof ProblemError && err.slug === "last_admin"
                          ? "deletion.err.raced"
                          : "state.error",
                      ),
                  });
                }}
              >
                {remove.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
                <Trans id="deletion.confirm" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={remove.isPending}
                onClick={() => setArmed(false)}
              >
                <Trans id="deletion.cancel" />
              </Button>
            </div>
          )}
        </div>
      )}

      {failure ? (
        <p role="alert" className="text-sm text-rost">
          {i18n._(failure)}
        </p>
      ) : null}
    </section>
  );
}
