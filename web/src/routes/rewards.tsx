import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import {
  useBalance,
  useCreateReward,
  useDeleteReward,
  useFulfillRedemption,
  useRedeemReward,
  useRedemptions,
  useRewards,
} from "../economy/queries";
import { ErrorState, LoadingState } from "../components/states";

// Belohnungskatalog (KONZEPT §5.9): members redeem rewards for points; admins curate the catalog
// and confirm redemptions. Auth-gated.
export function RewardsPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const balance = useBalance();
  const rewards = useRewards();
  const redemptions = useRedemptions();
  const redeem = useRedeemReward();
  const createReward = useCreateReward();
  const deleteReward = useDeleteReward();
  const fulfill = useFulfillRedemption();

  const [title, setTitle] = useState("");
  const [cost, setCost] = useState("10");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  const isAdmin = session.role === "admin";
  const myBalance = balance.data?.balance ?? 0;

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(cost);
    if (!title.trim() || value <= 0) return;
    createReward.mutate({ title: title.trim(), cost: value });
    setTitle("");
    setCost("10");
  };

  const pending = redemptions.data?.filter((r) => r.status === "requested") ?? [];

  return (
    <section aria-labelledby="rewards-heading" className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <h1 id="rewards-heading" className="font-display text-2xl">
          <Trans id="rewards.section" />
        </h1>
        <span className="shrink-0 rounded-full bg-laurus/10 px-3 py-1 text-sm font-medium text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark">
          {myBalance} <Trans id="tasks.pointsUnit" />
        </span>
      </div>

      {/* Catalog */}
      {rewards.isLoading ? (
        <LoadingState />
      ) : rewards.isError ? (
        <ErrorState />
      ) : rewards.data && rewards.data.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {rewards.data.map((reward) => {
            const affordable = myBalance >= reward.cost;
            const soldOut = reward.stock !== null && reward.stock <= 0;
            return (
              <li
                key={reward.id}
                className="flex flex-col justify-between gap-3 rounded-lg border border-stein/30 p-4"
              >
                <div>
                  <span className="font-display text-lg text-tinte dark:text-kalk">{reward.title}</span>
                  {reward.description ? (
                    <span className="mt-1 block text-sm text-stein-text">{reward.description}</span>
                  ) : null}
                  <span className="mt-1 block text-sm text-laurus dark:text-laurus-dark">
                    {reward.cost} <Trans id="tasks.pointsUnit" />
                    {reward.stock !== null ? (
                      <span className="ml-2 text-stein-text">
                        <Trans id="rewards.stock" />: {reward.stock}
                      </span>
                    ) : null}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => redeem.mutate(reward.id)}
                    disabled={!affordable || soldOut || redeem.isPending}
                  >
                    <Trans id="rewards.redeem" />
                  </Button>
                  {isAdmin ? (
                    <button
                      type="button"
                      onClick={() => deleteReward.mutate(reward.id)}
                      className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                    >
                      <Trans id="rewards.delete" />
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="rounded-md border border-stein/30 p-6 text-stein-text">
          <Trans id="rewards.empty" />
        </div>
      )}

      {/* Admin: create reward + confirm list */}
      {isAdmin ? (
        <>
          <section aria-labelledby="new-reward-heading" className="space-y-3">
            <h2 id="new-reward-heading" className="font-display text-lg">
              <Trans id="rewards.add" />
            </h2>
            <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
              <Field
                id="reward-title"
                label={<Trans id="rewards.title" />}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <Field
                id="reward-cost"
                type="number"
                min={1}
                label={<Trans id="rewards.cost" />}
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                className="w-28"
              />
              <Button type="submit" disabled={createReward.isPending || !title.trim()}>
                <Trans id="rewards.add" />
              </Button>
            </form>
          </section>

          <section aria-labelledby="pending-heading" className="space-y-3">
            <h2 id="pending-heading" className="font-display text-lg">
              <Trans id="rewards.pending" />
            </h2>
            {pending.length > 0 ? (
              <ul className="space-y-2">
                {pending.map((r) => (
                  <li
                    key={r.id}
                    className="flex items-center justify-between gap-4 rounded-md border border-stein/20 px-3 py-2"
                  >
                    <span className="text-tinte dark:text-kalk">
                      {r.title}{" "}
                      <span className="text-sm text-stein-text">
                        ({r.cost} <Trans id="tasks.pointsUnit" />)
                      </span>
                    </span>
                    <Button onClick={() => fulfill.mutate(r.id)} disabled={fulfill.isPending}>
                      <Trans id="rewards.fulfill" />
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-stein-text">
                <Trans id="rewards.noPending" />
              </p>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}
