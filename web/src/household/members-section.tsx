// Who lives in this household, and the two things one can do about it (KONZEPT §5.1).
//
// Lives on /account next to invites and child creation, because that is where the household is
// administered. The person's *own* rights (export, account deletion) stay on /profile — those
// belong to the person, not to the household.
//
// Roles are a <select>, not a menu of buttons: the set is closed (admin/member/child/guest) and a
// native control gets keyboard and screen-reader behaviour for free. Removal and leaving both go
// through window.confirm, like every other destructive action in the app (sessions, passkeys).
//
// The last-admin guard is the server's, not this component's. The UI does not pre-disable the
// admin's own "leave" button on a guess about the roster — it shows the server's reason, which is
// the one that is actually authoritative and which distinguishes three cases the client would
// have to re-derive (see errors.ts).

import { Trans, useLingui } from "@lingui/react";
import { Loader2 } from "lucide-react";
import { useState } from "react";

import type { MemberResponse, Role } from "../api/types.gen";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { memberProblemMessage, type MessageRef } from "./errors";
import { useChangeMemberRole, useLeaveHousehold, useMembers, useRemoveMember } from "./queries";

const ASSIGNABLE_ROLES: Role[] = ["admin", "member", "child", "guest"];

type Props = {
  isAdmin: boolean;
  /** The caller's own user id, so their row can be labelled and their own removal button hidden —
   *  leaving is a different act with different rules and has its own button. */
  selfUserId: string | null;
  onLeft: () => void;
};

export function MembersSection({ isAdmin, selfUserId, onLeft }: Props) {
  const { i18n } = useLingui();
  const members = useMembers();
  const changeRole = useChangeMemberRole();
  const removeMember = useRemoveMember();
  const leave = useLeaveHousehold();
  const [failure, setFailure] = useState<MessageRef | null>(null);

  // One place that turns a rejected mutation into a message, so the three call sites below stay
  // readable and none of them can forget to clear the previous failure first.
  const onError = (err: unknown) => setFailure(memberProblemMessage(err));

  // Aus dem Server-Bestand, nicht aus dem Token: ein `role`-Claim im Access-Token kann veraltet
  // sein (es wird je Anfrage nicht gegen die Datenbank geprüft).
  const selfRole = (members.data ?? []).find((m) => m.user_id === selfUserId)?.role;

  return (
    <section aria-labelledby="members-heading" className="space-y-3">
      <h3 id="members-heading" className="font-medium">
        <Trans id="members.title" />
      </h3>

      {members.isLoading ? (
        <LoadingState />
      ) : members.isError ? (
        <ErrorState />
      ) : (members.data ?? []).length === 0 ? (
        <EmptyState>
          <Trans id="members.empty" />
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {(members.data ?? []).map((member: MemberResponse) => {
            const isSelf = member.user_id === selfUserId;
            const busy =
              (changeRole.isPending && changeRole.variables?.membershipId === member.membership_id) ||
              (removeMember.isPending && removeMember.variables === member.membership_id);
            return (
              <li
                key={member.membership_id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-stein/20 px-3 py-2"
              >
                <span className="grow font-medium">
                  {member.display_name}
                  {isSelf ? (
                    <span className="ml-2 text-sm text-stein-text">
                      <Trans id="members.you" />
                    </span>
                  ) : null}
                </span>

                {isAdmin ? (
                  <label className="flex items-center gap-2 text-sm">
                    <span className="sr-only">
                      {i18n._("members.roleLabel", { name: member.display_name })}
                    </span>
                    <select
                      className="rounded-md border border-stein/30 bg-transparent px-2 py-1"
                      value={member.role}
                      disabled={busy}
                      onChange={(event) => {
                        setFailure(null);
                        changeRole.mutate(
                          {
                            membershipId: member.membership_id,
                            role: event.target.value as Role,
                          },
                          { onError },
                        );
                      }}
                    >
                      {ASSIGNABLE_ROLES.map((role) => (
                        <option key={role} value={role}>
                          {i18n._(`members.role.${role}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="text-sm text-stein-text">{i18n._(`members.role.${member.role}`)}</span>
                )}

                {isAdmin && !isSelf ? (
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          i18n._("members.confirmRemove", { name: member.display_name }),
                        )
                      ) {
                        setFailure(null);
                        removeMember.mutate(member.membership_id, { onError });
                      }
                    }}
                  >
                    {busy ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
                    <Trans id="members.remove" />
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {/* Leaving is the person's own act — but offered only once the roster has actually arrived,
          and never to a child.
          `isSuccess`, not `!isLoading`: a query that is paused (offline) is neither loading nor
          loaded, and `isLoading` is false in that state — the button would appear without anything
          having been asked.
          A child account has no e-mail and no password, `child_login` needs a live membership, and
          an invite needs a session it cannot create. Leaving would lock it out for good, so the
          server refuses (`child_cannot_leave`). Hidden rather than disabled: there is nothing the
          child could do to enable it, and removal by an adult is the way. */}
      {members.isSuccess && selfRole !== "child" ? (
        <div className="border-t border-stein/20 pt-3">
          <Button
            type="button"
            variant="danger"
            size="sm"
            disabled={leave.isPending}
            onClick={() => {
              if (window.confirm(i18n._("members.confirmLeave"))) {
                setFailure(null);
                leave.mutate(undefined, { onSuccess: onLeft, onError });
              }
            }}
          >
            {leave.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
            <Trans id="members.leave" />
          </Button>
          <p className="mt-2 text-sm text-stein-text">
            <Trans id="members.leaveHint" />
          </p>
        </div>
      ) : null}

      {failure ? (
        <p role="alert" className="text-sm text-rost">
          <Trans id={failure.id} />
          {failure.reference ? (
            <span className="ml-1 font-mono text-xs">({failure.reference})</span>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}
