import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, expect, test } from "vitest";

import { db } from "../shopping/db";
import { useShoppingBasics, useShoppingCatalog, useShoppingLists } from "../shopping/queries";

// Regression for BUGLOG 2026-07-19: db.lists.orderBy("name") threw SchemaError ("name" is not
// indexed on lists), so the lists query silently error-stated and the shopping UI showed
// "empty" forever, no matter what the cache held. These tests drive the REAL hooks against the
// real Dexie schema (fake-indexeddb) — a queryFn that throws turns isError true and fails here.

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client: qc }, children);
}

beforeEach(async () => {
  await Promise.all(db.tables.map((t) => t.clear()));
});

test("useShoppingLists resolves against the real schema, sorted by name", async () => {
  await db.lists.bulkPut([
    { id: "l2", name: "Wochenende", category_order: [] },
    { id: "l1", name: "Einkaufsliste", category_order: [] },
  ]);
  const { result } = renderHook(() => useShoppingLists(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.map((l) => l.name)).toEqual(["Einkaufsliste", "Wochenende"]);
});

test("catalog and basics queries resolve against the real schema", async () => {
  await db.catalog.put({ label: "Milch", category: null, count: 2, last_used: 1 });
  await db.basics.put({ id: "b1", label: "Brot", category: null });
  const catalog = renderHook(() => useShoppingCatalog(), { wrapper });
  const basics = renderHook(() => useShoppingBasics(), { wrapper });
  await waitFor(() => expect(catalog.result.current.isSuccess).toBe(true));
  await waitFor(() => expect(basics.result.current.isSuccess).toBe(true));
  expect(catalog.result.current.data?.[0]?.label).toBe("Milch");
  expect(basics.result.current.data?.[0]?.label).toBe("Brot");
});
