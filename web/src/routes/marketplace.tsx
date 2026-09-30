import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { useBalance } from "../economy/queries";
import { i18n } from "../i18n";
import {
  useAcceptListing,
  useAutoAcceptRules,
  useCreateListing,
  useCreateRule,
  useDeleteRule,
  useListings,
  useSettleListing,
  useWithdrawListing,
} from "../marketplace/queries";
import { useTaskInstances, useTaskTemplates } from "../tasks/queries";

// Marketplace (KONZEPT §5.10): trade assigned tasks. List one of your open tasks (price into escrow),
// accept others', withdraw your own, settle once the task is done. Auth-gated.
export function MarketplacePage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const balance = useBalance();
  const listings = useListings();
  const instances = useTaskInstances();
  const create = useCreateListing();
  const accept = useAcceptListing();
  const withdraw = useWithdrawListing();
  const settle = useSettleListing();
  const templates = useTaskTemplates();
  const rules = useAutoAcceptRules();
  const createRule = useCreateRule();
  const deleteRule = useDeleteRule();

  const [instanceId, setInstanceId] = useState("");
  const [price, setPrice] = useState("5");
  const [ruleTemplate, setRuleTemplate] = useState("");
  const [ruleMaxPrice, setRuleMaxPrice] = useState("10");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  const me = session.user_id;

  // Sellable = my open instances not already listed.
  const listedInstanceIds = new Set(
    (listings.data ?? []).filter((l) => l.status === "open").map((l) => l.task_instance_id),
  );
  const sellable = (instances.data ?? []).filter(
    (i) => i.assigned_to === me && !listedInstanceIds.has(i.id),
  );

  const handleList = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(price);
    if (!instanceId || value < 1) return;
    create.mutate({ task_instance_id: instanceId, price: value });
    setInstanceId("");
    setPrice("5");
  };

  const templateTitle = (id: string | null) =>
    id ? (templates.data ?? []).find((t) => t.id === id)?.title : null;

  const handleAddRule = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(ruleMaxPrice);
    if (value < 1) return;
    createRule.mutate({
      template_id: ruleTemplate || null,
      max_price: value,
    });
    setRuleTemplate("");
    setRuleMaxPrice("10");
  };

  return (
    <section aria-labelledby="market-heading" className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <h1 id="market-heading" className="font-display text-2xl">
          <Trans id="market.section" />
        </h1>
        <span className="shrink-0 rounded-full bg-laurus/10 px-3 py-1 text-sm font-medium text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark">
          {balance.data?.balance ?? 0} <Trans id="tasks.pointsUnit" />
        </span>
      </div>

      {/* Open + active listings */}
      {listings.isLoading ? (
        <LoadingState />
      ) : listings.isError ? (
        <ErrorState />
      ) : listings.data && listings.data.length > 0 ? (
        <ul className="space-y-3">
          {listings.data.map((l) => {
            const mine = l.seller_id === me;
            return (
              <li
                key={l.id}
                className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 p-4"
              >
                <div>
                  <span className="font-display text-lg text-tinte dark:text-kalk">{l.title}</span>
                  <span className="mt-1 block text-sm text-stein-text">
                    {l.price} <Trans id="tasks.pointsUnit" /> ·{" "}
                    <span className="uppercase tracking-wide">{l.status}</span>
                  </span>
                </div>
                <div className="flex shrink-0 gap-2">
                  {l.status === "open" && !mine ? (
                    <Button onClick={() => accept.mutate(l.id)} disabled={accept.isPending}>
                      <Trans id="market.accept" />
                    </Button>
                  ) : null}
                  {l.status === "open" && mine ? (
                    <button
                      type="button"
                      onClick={() => withdraw.mutate(l.id)}
                      className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                    >
                      <Trans id="market.withdraw" />
                    </button>
                  ) : null}
                  {l.status === "accepted" ? (
                    <Button onClick={() => settle.mutate(l.id)} disabled={settle.isPending}>
                      <Trans id="market.settle" />
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState>
          <Trans id="market.empty" />
        </EmptyState>
      )}

      {/* List one of my tasks */}
      {sellable.length > 0 ? (
        <section aria-labelledby="sell-heading" className="space-y-3">
          <h2 id="sell-heading" className="font-display text-lg">
            <Trans id="market.sell" />
          </h2>
          <form onSubmit={handleList} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label htmlFor="sell-task" className="block text-sm font-medium text-tinte dark:text-kalk">
                <Trans id="market.task" />
              </label>
              <select
                id="sell-task"
                value={instanceId}
                onChange={(e) => setInstanceId(e.target.value)}
                className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
              >
                <option value="">{i18n._("market.pickTask")}</option>
                {sellable.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.title}
                  </option>
                ))}
              </select>
            </div>
            <Field
              id="sell-price"
              type="number"
              min={1}
              label={<Trans id="market.price" />}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="w-24"
            />
            <Button type="submit" disabled={create.isPending || !instanceId}>
              <Trans id="market.list" />
            </Button>
          </form>
        </section>
      ) : null}

      {/* Auto-accept rules: matching listings get picked up for me automatically. */}
      <section aria-labelledby="rules-heading" className="space-y-3 border-t border-stein/20 pt-6">
        <h2 id="rules-heading" className="font-display text-lg">
          <Trans id="market.rules" />
        </h2>
        <p className="text-sm text-stein-text">
          <Trans id="market.rulesHint" />
        </p>
        {rules.isLoading ? (
          <LoadingState />
        ) : rules.isError ? (
          <ErrorState />
        ) : rules.data && rules.data.length > 0 ? (
          <ul className="space-y-2">
            {rules.data.map((r) => (
              <li
                key={r.id}
                className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 px-4 py-2"
              >
                <span className="text-sm text-tinte dark:text-kalk">
                  {templateTitle(r.template_id) ?? i18n._("market.anyTask")} ·{" "}
                  <Trans id="market.upTo" /> {r.max_price} <Trans id="tasks.pointsUnit" />
                </span>
                <button
                  type="button"
                  onClick={() => deleteRule.mutate(r.id)}
                  disabled={deleteRule.isPending}
                  className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                >
                  <Trans id="market.removeRule" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>
            <Trans id="market.rulesEmpty" />
          </EmptyState>
        )}
        <form onSubmit={handleAddRule} className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor="rule-template" className="block text-sm font-medium text-tinte dark:text-kalk">
              <Trans id="market.task" />
            </label>
            <select
              id="rule-template"
              value={ruleTemplate}
              onChange={(e) => setRuleTemplate(e.target.value)}
              className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            >
              <option value="">{i18n._("market.anyTask")}</option>
              {(templates.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </div>
          <Field
            id="rule-max-price"
            type="number"
            min={1}
            label={<Trans id="market.maxPrice" />}
            value={ruleMaxPrice}
            onChange={(e) => setRuleMaxPrice(e.target.value)}
            className="w-24"
          />
          <Button type="submit" disabled={createRule.isPending}>
            <Trans id="market.addRule" />
          </Button>
        </form>
      </section>
    </section>
  );
}
