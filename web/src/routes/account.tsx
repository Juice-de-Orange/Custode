import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import {
  ProblemError,
  useCreateChild,
  useCreateHousehold,
  useCreateInvite,
  useHouseholds,
  useJoinHousehold,
  useLogout,
  useRequestEmailVerification,
  useSession,
  useSwitchHousehold,
} from "../auth/session";
import { Button } from "../components/button";
import { ChildCreateForm } from "../components/child-create-form";
import { VerificationBanner } from "../components/verification-banner";
import { DigestToggle } from "../components/digest-toggle";
import { HouseholdCreateForm } from "../components/household-create-form";
import { HouseholdJoinForm } from "../components/household-join-form";
import { HouseholdsList } from "../components/households-list";
import { ErrorState, LoadingState } from "../components/states";
import { DissolveSection } from "../household/dissolve-section";
import { MembersSection } from "../household/members-section";

const JOIN_CODE_ERRORS = ["not_found", "invite_expired", "invite_exhausted", "already_member"];

// Protected landing: identity (GET /v1/auth/me) + household management (list, create,
// switch, join, invite). Redirects to /login when no session is present.
export function AccountPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useSession();
  const logout = useLogout();
  const households = useHouseholds();
  const createHousehold = useCreateHousehold();
  const switchHousehold = useSwitchHousehold();
  const joinHousehold = useJoinHousehold();
  const createInvite = useCreateInvite();
  const createChild = useCreateChild();
  const requestVerify = useRequestEmailVerification();
  const [createError, setCreateError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [verifySent, setVerifySent] = useState(false);
  const [childError, setChildError] = useState<string | null>(null);
  const [createdChild, setCreatedChild] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && data === null) {
      navigate({ to: "/login" });
    }
  }, [isLoading, data, navigate]);

  if (isLoading || data === null) return <LoadingState />;
  if (isError || data === undefined) return <ErrorState />;

  return (
    <section aria-labelledby="account-heading" className="space-y-10">
      {data.email_verified ? null : (
        <VerificationBanner
          pending={requestVerify.isPending}
          sent={verifySent}
          onResend={() =>
            requestVerify.mutate(undefined, { onSettled: () => setVerifySent(true) })
          }
        />
      )}
      <div className="space-y-6">
        <h1 id="account-heading" className="font-display text-2xl">
          <Trans id="account.title" />
        </h1>
        <dl className="space-y-3">
          <div>
            <dt className="text-sm text-stein-text">
              <Trans id="account.loggedInAs" />
            </dt>
            <dd className="font-medium">{data.email}</dd>
          </div>
          <div>
            <dt className="text-sm text-stein-text">
              <Trans id="account.role" />
            </dt>
            <dd>{data.role ?? <Trans id="account.none" />}</dd>
          </div>
          <div>
            <dd>
              <Trans id={data.totp_enabled ? "account.totpOn" : "account.totpOff"} />
            </dd>
            <dd>
              <Link to="/security" className="text-sm text-laurus dark:text-laurus-dark hover:underline">
                <Trans id="security.openLink" />
              </Link>
            </dd>
            <dd>
              <Link to="/profile" className="text-sm text-laurus dark:text-laurus-dark hover:underline">
                <Trans id="profile.link" />
              </Link>
            </dd>
          </div>
        </dl>
        <Button
          type="button"
          disabled={logout.isPending}
          onClick={() => logout.mutate(undefined, { onSuccess: () => navigate({ to: "/login" }) })}
        >
          <Trans id="account.logout" />
        </Button>
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-xl">
          <Trans id="household.section" />
        </h2>
        {households.isLoading ? (
          <LoadingState />
        ) : (
          <HouseholdsList
            households={households.data ?? []}
            activeId={data.household_id ?? null}
            onSwitch={(id) => switchHousehold.mutate(id)}
            pendingId={switchHousehold.isPending ? (switchHousehold.variables ?? null) : null}
          />
        )}

        {/* Only with an active household: the roster is RLS-scoped to it, and without one the
            backend has nothing to answer. Every role sees the list and the leave button — the
            server decides who may actually go, and says why not. */}
        {data.household_id ? (
          <MembersSection
            isAdmin={data.role === "admin"}
            selfUserId={data.user_id}
            onLeft={() => navigate({ to: "/login" })}
          />
        ) : null}

        {data.role === "admin" ? (
          <div className="space-y-2">
            <DigestToggle isAdmin={data.role === "admin"} />
            <Button
              type="button"
              disabled={createInvite.isPending}
              onClick={() => createInvite.mutate()}
            >
              <Trans id="household.invite" />
            </Button>
            {createInvite.data ? (
              <p className="text-sm">
                <Trans id="household.inviteHint" />{" "}
                <code className="rounded bg-stein/10 px-1.5 py-0.5 font-mono">
                  {createInvite.data.code}
                </code>
              </p>
            ) : null}
            <div className="space-y-3 border-t border-stein/20 pt-4">
              <h3 className="font-medium">
                <Trans id="child.section" />
              </h3>
              <ChildCreateForm
                pending={createChild.isPending}
                error={childError}
                createdName={createdChild}
                onSubmit={(values) => {
                  setChildError(null);
                  setCreatedChild(null);
                  createChild.mutate(values, {
                    onSuccess: (child) => setCreatedChild(child.username),
                    onError: (err) => {
                      const slug = err instanceof ProblemError ? err.slug : "error";
                      setChildError(
                        slug === "username_taken"
                          ? "child.error.username"
                          : slug === "weak_pin"
                            ? "child.error.weakPin"
                            : "state.error",
                      );
                    },
                  });
                }}
              />
            </div>
          </div>
        ) : null}

        {/* Ganz unten und optisch abgesetzt — eine zerstörerische Aktion gehört nicht über die
            Bedienelemente, die man täglich benutzt. Sie beendet den Haushalt für alle und ist
            nicht rückgängig zu machen (ADR-0085). */}
        {data.household_id && data.role === "admin" ? (
          <DissolveSection onDissolved={() => navigate({ to: "/login" })} />
        ) : null}
      </div>

      <div className="grid gap-8 sm:grid-cols-2">
        <div className="space-y-3">
          <h3 className="font-medium">
            <Trans id="household.createTitle" />
          </h3>
          <HouseholdCreateForm
            pending={createHousehold.isPending}
            error={createError}
            onSubmit={(name) => {
              setCreateError(null);
              createHousehold.mutate({ name }, { onError: () => setCreateError("state.error") });
            }}
          />
        </div>
        <div className="space-y-3">
          <h3 className="font-medium">
            <Trans id="household.joinTitle" />
          </h3>
          <HouseholdJoinForm
            pending={joinHousehold.isPending}
            error={joinError}
            onSubmit={(code) => {
              setJoinError(null);
              joinHousehold.mutate(
                { code },
                {
                  onError: (err) => {
                    const slug = err instanceof ProblemError ? err.slug : "error";
                    setJoinError(JOIN_CODE_ERRORS.includes(slug) ? "household.error.code" : "state.error");
                  },
                },
              );
            }}
          />
        </div>
      </div>
    </section>
  );
}
