import { Trans, useLingui } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import type { LocalItem } from "../shopping/db";
import {
  useShoppingActions,
  useShoppingBasics,
  useShoppingCatalog,
  useShoppingItems,
  useShoppingLists,
  useShoppingSync,
} from "../shopping/queries";
import { listReadyForTrip, PLAN_INTENT_KEY } from "../shopping/ready";
import { sync } from "../shopping/sync";
import { useOnline } from "../lib/useOnline";

// Offline-first shopping list (P3-S4): reads the Dexie cache, writes optimistically via the sync
// engine. 1-tap check, add items, multiple lists; live across devices via the SSE "shopping" hint.
export function ShoppingPage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const { data: session, isLoading } = useSession();
  const online = useOnline();
  useShoppingSync();

  // Push the outbox as soon as connectivity returns (the shared hook stays side-effect-free).
  useEffect(() => {
    const onReconnect = () => void sync();
    window.addEventListener("online", onReconnect);
    return () => window.removeEventListener("online", onReconnect);
  }, []);

  const lists = useShoppingLists();
  const actions = useShoppingActions();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draftItem, setDraftItem] = useState("");
  const [draftList, setDraftList] = useState("");
  const [draftBasic, setDraftBasic] = useState("");

  useEffect(() => {
    if (!isLoading && session === null) navigate({ to: "/login" });
  }, [isLoading, session, navigate]);

  const activeList = lists.data?.find((l) => l.id === activeId) ?? lists.data?.[0] ?? null;
  const items = useShoppingItems(activeList?.id);
  const catalog = useShoppingCatalog();
  const basics = useShoppingBasics();

  if (isLoading || !session) return <LoadingState />;

  const open = (items.data ?? [])
    .filter((item) => !item.checked)
    .sort((a, b) => (a.category ?? "").localeCompare(b.category ?? "") || a.label.localeCompare(b.label));
  const done = (items.data ?? []).filter((item) => item.checked);

  const addItem = (event: FormEvent) => {
    event.preventDefault();
    const label = draftItem.trim();
    if (!label || !activeList) return;
    void actions.mutate({ type: "addItem", listId: activeList.id, label });
    setDraftItem("");
  };

  const createList = (event: FormEvent) => {
    event.preventDefault();
    const name = draftList.trim();
    if (!name) return;
    actions.mutate({ type: "createList", name }, { onSuccess: (id) => setActiveId(id ?? null) });
    setDraftList("");
  };

  const addBasic = (event: FormEvent) => {
    event.preventDefault();
    const label = draftBasic.trim();
    if (!label) return;
    void actions.mutate({ type: "addBasic", label });
    setDraftBasic("");
  };

  return (
    <section aria-labelledby="shopping-heading" className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="shopping-heading" className="font-display text-2xl">
          <Trans id="shopping.section" />
        </h1>
        {lists.data && lists.data.length > 0 ? (
          <select
            aria-label={i18n._("shopping.listSwitcher")}
            value={activeList?.id ?? ""}
            onChange={(event) => setActiveId(event.target.value)}
            className="rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk"
          >
            {lists.data.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {!online ? (
        <p role="status" className="rounded-md bg-bernstein/15 px-3 py-2 text-sm text-tinte dark:text-kalk">
          <Trans id="shopping.offline" />
        </p>
      ) : null}

      {/* S-17: a full enough list nudges toward scheduling a shopping slot. */}
      {listReadyForTrip(open.length) ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-laurus/40 bg-laurus/10 px-3 py-2 text-sm">
          <span className="text-tinte dark:text-kalk">
            {i18n._("shopping.tripReady", { count: open.length })}
          </span>
          <button
            type="button"
            onClick={() => {
              sessionStorage.setItem(PLAN_INTENT_KEY, "shopping");
              void navigate({ to: "/calendar" });
            }}
            className="font-medium text-laurus dark:text-laurus-dark hover:underline"
          >
            <Trans id="shopping.planTrip" />
          </button>
        </div>
      ) : null}

      {/* Trio gap closed (BUGLOG 2026-07-19): a failing primary query used to render as "empty".
          The list body distinguishes error from genuinely no lists before offering the first-list form. */}
      {lists.isError ? (
        <ErrorState />
      ) : lists.data && lists.data.length === 0 ? (
        <form onSubmit={createList} className="space-y-3">
          <EmptyState>
            <Trans id="shopping.noLists" />
          </EmptyState>
          <Field
            id="shopping-new-list"
            value={draftList}
            onChange={(event) => setDraftList(event.target.value)}
            placeholder={i18n._("shopping.firstListName")}
            label={<Trans id="shopping.listName" />}
          />
          <Button type="submit">
            <Trans id="shopping.createList" />
          </Button>
        </form>
      ) : (
        <>
          <form onSubmit={addItem} className="flex gap-2">
            <input
              aria-label={i18n._("shopping.addItem")}
              value={draftItem}
              onChange={(event) => setDraftItem(event.target.value)}
              placeholder={i18n._("shopping.itemPlaceholder")}
              className="block w-full rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            />
            <Button type="submit" className="shrink-0">
              <Trans id="shopping.add" />
            </Button>
          </form>

          {catalog.data && catalog.data.length > 0 ? (
            <div>
              <h2 className="text-sm font-medium text-stein-text">
                <Trans id="shopping.catalog" />
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {catalog.data
                  .filter((entry) => !open.some((it) => it.label === entry.label))
                  .slice(0, 12)
                  .map((entry) => (
                    <button
                      key={entry.label}
                      type="button"
                      onClick={() =>
                        activeList &&
                        actions.mutate({
                          type: "addItem",
                          listId: activeList.id,
                          label: entry.label,
                          category: entry.category,
                        })
                      }
                      className="rounded-full border border-stein/40 px-3 py-1 text-sm text-tinte dark:text-kalk hover:border-laurus hover:bg-laurus/10"
                    >
                      + {entry.label}
                    </button>
                  ))}
              </div>
            </div>
          ) : null}

          <div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-stein-text">
                <Trans id="shopping.basics" />
              </h2>
              <form onSubmit={addBasic} className="flex gap-2">
                <input
                  aria-label={i18n._("shopping.addBasic")}
                  value={draftBasic}
                  onChange={(event) => setDraftBasic(event.target.value)}
                  placeholder={i18n._("shopping.addBasicPlaceholder")}
                  className="rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
                />
                <Button type="submit" className="shrink-0">
                  +
                </Button>
              </form>
            </div>
            {basics.data && basics.data.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {basics.data.map((basic) => (
                  <span
                    key={basic.id}
                    className="inline-flex items-center gap-1 rounded-full border border-laurus/40 bg-laurus/5 pl-3 pr-1 text-sm"
                  >
                    <button
                      type="button"
                      onClick={() =>
                        activeList &&
                        actions.mutate({
                          type: "addItem",
                          listId: activeList.id,
                          label: basic.label,
                          category: basic.category,
                        })
                      }
                      className="py-1 text-tinte dark:text-kalk"
                    >
                      + {basic.label}
                    </button>
                    <button
                      type="button"
                      onClick={() => actions.mutate({ type: "removeBasic", id: basic.id })}
                      aria-label={i18n._("shopping.removeBasic")}
                      className="px-1 text-stein-text hover:text-rost"
                    >
                      <X className="size-4" aria-hidden="true" />
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          {items.isError ? (
            <ErrorState />
          ) : open.length === 0 && done.length === 0 ? (
            <EmptyState>
              <Trans id="shopping.empty" />
            </EmptyState>
          ) : (
            <ul className="space-y-1">
              {open.map((item) => (
                <ShoppingRow key={item.id} item={item} actions={actions} me={session.user_id} />
              ))}
              {done.length > 0 ? (
                <li className="pt-4 text-sm text-stein-text">
                  <Trans id="shopping.checked" />
                </li>
              ) : null}
              {done.map((item) => (
                <ShoppingRow key={item.id} item={item} actions={actions} me={session.user_id} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function ShoppingRow({
  item,
  actions,
  me,
}: {
  item: LocalItem;
  actions: ReturnType<typeof useShoppingActions>;
  me: string;
}) {
  const { i18n } = useLingui();
  return (
    <li className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-stein/5">
      <input
        type="checkbox"
        checked={item.checked}
        onChange={() => actions.mutate({ type: "toggle", item })}
        className="h-5 w-5 shrink-0 accent-laurus"
      />
      <span className={`flex-1 ${item.checked ? "text-stein-text line-through" : "text-tinte dark:text-kalk"}`}>
        {item.label}
        {item.category ? <span className="ml-2 text-xs text-stein-text">{item.category}</span> : null}
      </span>
      {item.reserved_by === null ? (
        <button
          type="button"
          onClick={() => actions.mutate({ type: "reserve", item, reservedBy: me })}
          className="shrink-0 text-xs text-stein-text hover:text-laurus dark:hover:text-laurus-dark"
        >
          {i18n._("shopping.reserve")}
        </button>
      ) : item.reserved_by === me ? (
        <button
          type="button"
          onClick={() => actions.mutate({ type: "reserve", item, reservedBy: null })}
          className="shrink-0 rounded-full bg-laurus/10 px-2 py-0.5 text-xs text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark"
        >
          {i18n._("shopping.reservedByYou")}
        </button>
      ) : (
        <span className="shrink-0 rounded-full bg-bernstein/15 px-2 py-0.5 text-xs text-stein-text">
          {i18n._("shopping.reserved")}
        </span>
      )}
      <button
        type="button"
        onClick={() => actions.mutate({ type: "delete", id: item.id })}
        aria-label={i18n._("shopping.delete")}
        className="shrink-0 text-stein-text hover:text-rost"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </li>
  );
}
