import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import {
  useChallenge,
  useFairness,
  useHouseholdMembers,
  useSendThanks,
} from "../economy/queries";
import { i18n } from "../i18n";

// Wochen-Challenge + Danke-Punkte (KONZEPT §5.9): live standings of points earned this week, and a
// thank-you transfer to another member (capped per week). Auth-gated.
export function ChallengePage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const challenge = useChallenge();
  const fairness = useFairness();
  const members = useHouseholdMembers();
  const thank = useSendThanks();

  const [toMember, setToMember] = useState("");
  const [amount, setAmount] = useState("1");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;

  const nameOf = (userId: string) =>
    members.data?.find((m) => m.user_id === userId)?.display_name ?? userId.slice(0, 8);
  const others = members.data?.filter((m) => m.user_id !== session.user_id) ?? [];
  const remaining = challenge.data?.thanks_remaining ?? 0;

  const handleThank = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(amount);
    if (!toMember || value < 1) return;
    thank.mutate({ to_member_id: toMember, amount: value });
    setAmount("1");
  };

  return (
    <section aria-labelledby="challenge-heading" className="space-y-8">
      <h1 id="challenge-heading" className="font-display text-2xl">
        <Trans id="challenge.section" />
      </h1>

      {/* Weekly standings */}
      <section aria-labelledby="standings-heading" className="space-y-3">
        <h2 id="standings-heading" className="font-display text-lg">
          <Trans id="challenge.standings" />
        </h2>
        {challenge.isLoading ? (
          <LoadingState />
        ) : challenge.isError ? (
          <ErrorState />
        ) : challenge.data && challenge.data.standings.length > 0 ? (
          <ol className="space-y-2">
            {challenge.data.standings.map((s, i) => (
              <li
                key={s.member_id}
                className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 px-4 py-3"
              >
                <span className="text-tinte dark:text-kalk">
                  <span className="mr-2 font-display text-stein-text">{i + 1}.</span>
                  {nameOf(s.member_id)}
                </span>
                <span className="font-medium text-laurus dark:text-laurus-dark">
                  {s.points} <Trans id="tasks.pointsUnit" />
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState>
            <Trans id="challenge.empty" />
          </EmptyState>
        )}
      </section>

      {/* Fairness account (lowest load = next in line) */}
      {fairness.data && fairness.data.entries.length > 0 ? (
        <section aria-labelledby="fairness-heading" className="space-y-3">
          <h2 id="fairness-heading" className="font-display text-lg">
            <Trans id="challenge.fairness" /> ({fairness.data.window_days} <Trans id="challenge.days" />)
          </h2>
          <ul className="space-y-2">
            {fairness.data.entries.map((e) => (
              <li
                key={e.member_id}
                className="flex items-center justify-between gap-4 rounded-md border border-stein/20 px-3 py-2"
              >
                <span className="text-tinte dark:text-kalk">{nameOf(e.member_id)}</span>
                <span className="text-sm text-stein-text">
                  {e.load} <Trans id="tasks.pointsUnit" />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Thank a member */}
      {others.length > 0 ? (
        <section aria-labelledby="thanks-heading" className="space-y-3">
          <h2 id="thanks-heading" className="font-display text-lg">
            <Trans id="challenge.thank" />
          </h2>
          <p className="text-sm text-stein-text">
            <Trans id="challenge.remaining" />: {remaining}
          </p>
          <form onSubmit={handleThank} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label htmlFor="thank-member" className="block text-sm font-medium text-tinte dark:text-kalk">
                <Trans id="challenge.member" />
              </label>
              <select
                id="thank-member"
                value={toMember}
                onChange={(e) => setToMember(e.target.value)}
                className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
              >
                <option value="">{i18n._("challenge.pickMember")}</option>
                {others.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </div>
            <Field
              id="thank-amount"
              type="number"
              min={1}
              max={remaining}
              label={<Trans id="challenge.amount" />}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-24"
            />
            <Button
              type="submit"
              disabled={thank.isPending || !toMember || remaining < 1}
            >
              <Trans id="challenge.send" />
            </Button>
          </form>
        </section>
      ) : null}
    </section>
  );
}
