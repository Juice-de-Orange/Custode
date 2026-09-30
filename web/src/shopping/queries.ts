import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { db, type LocalItem } from "./db";
import { enqueue, sync } from "./sync";

export const SHOPPING_QUERY_KEY = ["shopping"] as const;

function newId(): string {
  return crypto.randomUUID();
}

// Learn from each added item: bump its count, remember the category (for the quick-catalog tiles).
export async function recordCatalog(label: string, category: string | null): Promise<void> {
  const existing = await db.catalog.get(label);
  await db.catalog.put({
    label,
    category: category ?? existing?.category ?? null,
    count: (existing?.count ?? 0) + 1,
    last_used: Date.now(),
  });
}

// Reads come from the local Dexie cache (offline-first). Mutations write optimistically + queue, then
// invalidate so the UI re-reads. Background sync (push/pull) reconciles with the server.
export function useShoppingLists() {
  return useQuery({
    queryKey: [...SHOPPING_QUERY_KEY, "lists"],
    // Sort in JS: ``lists`` only indexes the primary key ("id"), and Dexie's orderBy() THROWS
    // SchemaError on non-indexed keys — which silently error-states this query and blanks the
    // whole shopping UI (BUGLOG 2026-07-19). A handful of lists needs no index.
    queryFn: async () =>
      (await db.lists.toArray()).sort((a, b) => a.name.localeCompare(b.name)),
  });
}

export function useShoppingItems(listId: string | undefined) {
  return useQuery({
    queryKey: [...SHOPPING_QUERY_KEY, "items", listId ?? null],
    queryFn: () =>
      listId
        ? db.items.where("list_id").equals(listId).toArray()
        : Promise.resolve<LocalItem[]>([]),
    enabled: Boolean(listId),
  });
}

// Count of still-open (unchecked) items across all lists, for the „Heute" dashboard tile.
// Reads the offline cache; pair with `useShoppingSync()` so it reflects the server state.
export function useShoppingOpenCount() {
  return useQuery({
    queryKey: [...SHOPPING_QUERY_KEY, "open-count"],
    queryFn: () => db.items.filter((item) => !item.checked).count(),
  });
}

// The learned quick-catalog: most-used labels first (1-tap re-add, T4).
export function useShoppingCatalog() {
  return useQuery({
    queryKey: [...SHOPPING_QUERY_KEY, "catalog"],
    queryFn: () => db.catalog.orderBy("count").reverse().limit(16).toArray(),
  });
}

// Basics: the household's curated staples (synced), alphabetical.
export function useShoppingBasics() {
  return useQuery({
    queryKey: [...SHOPPING_QUERY_KEY, "basics"],
    queryFn: () => db.basics.orderBy("label").toArray(),
  });
}

// Pull the latest into Dexie once on mount (and re-read). Live cross-device updates arrive via the
// SSE "shopping" hint (realtime), which also triggers a sync.
export function useShoppingSync(): void {
  const qc = useQueryClient();
  useEffect(() => {
    void sync()
      .then(() => qc.invalidateQueries({ queryKey: SHOPPING_QUERY_KEY }))
      .catch(() => undefined);
  }, [qc]);
}

export function useShoppingActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: SHOPPING_QUERY_KEY });

  return useMutation({
    mutationFn: async (action: ShoppingAction): Promise<string | void> => {
      if (action.type === "createList") {
        const id = newId();
        await enqueue(
          "shopping_list",
          id,
          "upsert",
          { name: action.name, category_order: [] },
          async () => {
            await db.lists.put({ id, name: action.name, category_order: [] });
          },
        );
        return id;
      }
      if (action.type === "addItem") {
        const id = newId();
        await enqueue(
          "shopping_item",
          id,
          "upsert",
          { list_id: action.listId, label: action.label, category: action.category ?? null },
          async () => {
            await db.items.put({
              id,
              list_id: action.listId,
              label: action.label,
              qty: null,
              unit: null,
              category: action.category ?? null,
              checked: false,
              source: "manual",
              notes: null,
              reserved_by: null,
              checked_by: null,
            });
          },
        );
        await recordCatalog(action.label, action.category ?? null);
        return id;
      }
      if (action.type === "toggle") {
        const next = !action.item.checked;
        await enqueue(
          "shopping_item",
          action.item.id,
          "upsert",
          { checked: next },
          async () => {
            await db.items.update(action.item.id, { checked: next });
          },
        );
        return;
      }
      if (action.type === "addBasic") {
        const id = newId();
        await enqueue(
          "shopping_basic",
          id,
          "upsert",
          { label: action.label, category: action.category ?? null },
          async () => {
            await db.basics.put({ id, label: action.label, category: action.category ?? null });
          },
        );
        return id;
      }
      if (action.type === "removeBasic") {
        await enqueue("shopping_basic", action.id, "delete", {}, async () => {
          await db.basics.delete(action.id);
        });
        return;
      }
      if (action.type === "reserve") {
        // The server stamps reserved_by from the session; we optimistically mirror it.
        await enqueue(
          "shopping_item",
          action.item.id,
          "upsert",
          { reserve: action.reservedBy !== null },
          async () => {
            await db.items.update(action.item.id, { reserved_by: action.reservedBy });
          },
        );
        return;
      }
      // delete item
      await enqueue("shopping_item", action.id, "delete", {}, async () => {
        await db.items.delete(action.id);
      });
    },
    onSuccess: () => {
      void invalidate();
    },
  });
}

export type ShoppingAction =
  | { type: "createList"; name: string }
  | { type: "addItem"; listId: string; label: string; category?: string | null }
  | { type: "toggle"; item: LocalItem }
  | { type: "addBasic"; label: string; category?: string | null }
  | { type: "removeBasic"; id: string }
  | { type: "reserve"; item: LocalItem; reservedBy: string | null }
  | { type: "delete"; id: string };
