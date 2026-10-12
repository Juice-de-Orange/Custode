import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("../api/client.gen", () => ({
  client: { post: vi.fn(), get: vi.fn() },
}));

import type { MeResponse } from "../api/types.gen";
import { client } from "../api/client.gen";
import { fetchMe, useSession } from "../auth/session";
import { db, rememberSession } from "../shopping/db";
import { useShoppingActions, useShoppingItems, useShoppingLists } from "../shopping/queries";

// "The shopping list works offline in the shop" (README). Everything the shopping hooks do is
// local — Dexie plus the outbox; the network push is fire-and-forget. React Query's default
// networkMode "online" PAUSED these hooks while offline, so an item added in the shop never
// reached Dexie or the outbox, and a reload offline hung on the session query (BUGLOG
// 2026-10-12). The browser test e2e/offline-shopping.e2e.ts covers the whole path.

const post = client.post as unknown as ReturnType<typeof vi.fn>;
const get = client.get as unknown as ReturnType<typeof vi.fn>;

// What the generated client returns when fetch itself fails: an error and no response.
const OFFLINE = { data: undefined, error: new TypeError("Failed to fetch"), response: undefined };

const ME: MeResponse = {
  user_id: "u1",
  email: "a@example.org",
  display_name: "A",
  household_id: "h1",
  role: "admin",
  totp_enabled: false,
  recovery_codes_remaining: 0,
  email_verified: true,
  mail_enabled: false,
  flags: {},
};

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client: qc }, children);
}

beforeEach(async () => {
  await Promise.all(db.tables.map((t) => t.clear()));
  post.mockReset();
  get.mockReset();
  post.mockResolvedValue(OFFLINE);
  get.mockResolvedValue(OFFLINE);
  onlineManager.setOnline(false);
});

afterEach(() => {
  onlineManager.setOnline(true);
});

test("adding and checking off an item offline writes Dexie and the outbox", async () => {
  await db.lists.put({ id: "l1", name: "Weekly", category_order: [] });
  const { result } = renderHook(() => useShoppingActions(), { wrapper });

  let id: string | void = undefined;
  await act(async () => {
    id = await result.current.mutateAsync({ type: "addItem", listId: "l1", label: "Oat milk" });
  });
  const added = await db.items.get(id as unknown as string);
  expect(added).toMatchObject({ label: "Oat milk", checked: false });

  await act(async () => {
    await result.current.mutateAsync({ type: "toggle", item: added! });
  });
  expect(await db.items.get(added!.id)).toMatchObject({ checked: true });
  expect(await db.outbox.count()).toBe(2);
});

test("the list and its items read from Dexie while offline", async () => {
  await db.lists.put({ id: "l1", name: "Weekly", category_order: [] });
  await db.items.put({
    id: "i1",
    list_id: "l1",
    label: "Apples",
    qty: null,
    unit: null,
    category: null,
    checked: true,
    source: "manual",
    notes: null,
    reserved_by: null,
    checked_by: null,
  });
  const lists = renderHook(() => useShoppingLists(), { wrapper });
  const items = renderHook(() => useShoppingItems("l1"), { wrapper });
  await waitFor(() => expect(lists.result.current.isSuccess).toBe(true));
  await waitFor(() => expect(items.result.current.isSuccess).toBe(true));
  expect(items.result.current.data?.[0]).toMatchObject({ label: "Apples", checked: true });
});

test("offline, the session falls back to the one remembered on this device", async () => {
  await rememberSession(ME);
  expect(await fetchMe()).toEqual(ME);

  const { result } = renderHook(() => useSession(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.user_id).toBe("u1");
});

test("offline without a remembered session, fetchMe still fails instead of inventing one", async () => {
  await expect(fetchMe()).rejects.toThrow();
});

test("a server answer is never replaced by the remembered session", async () => {
  await rememberSession(ME);
  get.mockResolvedValue({ data: undefined, error: {}, response: new Response(null, { status: 401 }) });
  expect(await fetchMe()).toBeNull();
});
