import { beforeEach, expect, test, vi } from "vitest";

vi.mock("../api/client.gen", () => ({
  client: { post: vi.fn(), get: vi.fn() },
}));

import { client } from "../api/client.gen";
import { db, type LocalItem } from "../shopping/db";
import { enqueue, pull, push, sync } from "../shopping/sync";

const post = client.post as unknown as ReturnType<typeof vi.fn>;
const get = client.get as unknown as ReturnType<typeof vi.fn>;

const OFFLINE = { data: undefined, error: new Error("offline"), response: undefined };

function item(id: string, label: string, checked = false): LocalItem {
  return {
    id,
    list_id: "l1",
    label,
    qty: null,
    unit: null,
    category: null,
    checked,
    source: "manual",
    notes: null,
    reserved_by: null,
    checked_by: null,
  };
}

beforeEach(async () => {
  await Promise.all([
    db.lists.clear(),
    db.items.clear(),
    db.outbox.clear(),
    db.meta.clear(),
    db.basics.clear(),
  ]);
  post.mockReset();
  get.mockReset();
  post.mockResolvedValue(OFFLINE);
  get.mockResolvedValue(OFFLINE);
});

test("enqueue applies optimistically and queues an outbox op", async () => {
  await enqueue(
    "shopping_item",
    "i1",
    "upsert",
    { list_id: "l1", label: "Milch" },
    async () => {
      await db.items.put(item("i1", "Milch"));
    },
  );
  expect(await db.items.get("i1")).toMatchObject({ label: "Milch" });
  expect(await db.outbox.count()).toBe(1);
});

test("push applies authoritative server state and clears the queue", async () => {
  await db.outbox.add({
    client_op_id: "op-1",
    entity: "shopping_item",
    entity_id: "i1",
    op: "upsert",
    fields: { list_id: "l1", label: "Milch" },
    created_at: 1,
  });
  post.mockResolvedValue({
    data: {
      applied: [
        {
          entity: "shopping_item",
          id: "i1",
          version: 1,
          deleted: false,
          fields: { list_id: "l1", label: "Milch", checked: true },
        },
      ],
    },
    error: undefined,
    response: { status: 200 },
  });
  await push();
  expect(post).toHaveBeenCalledOnce();
  expect(await db.items.get("i1")).toMatchObject({ checked: true });
  expect(await db.outbox.count()).toBe(0);
});

test("offline push keeps the queue", async () => {
  await db.outbox.add({
    client_op_id: "op-1",
    entity: "shopping_item",
    entity_id: "i1",
    op: "upsert",
    fields: {},
    created_at: 1,
  });
  await push(); // OFFLINE default
  expect(await db.outbox.count()).toBe(1);
});

test("pull applies changes and stores the cursor", async () => {
  get.mockResolvedValue({
    data: {
      changes: [
        { entity: "shopping_item", id: "i1", op: "upsert", fields: { list_id: "l1", label: "Brot" } },
      ],
      next_cursor: "c1",
    },
    error: undefined,
    response: { status: 200 },
  });
  await pull();
  expect(await db.items.get("i1")).toMatchObject({ label: "Brot" });
  expect((await db.meta.get("cursor"))?.value).toBe("c1");
});

test("pull op=delete removes the local row", async () => {
  await db.items.put(item("i1", "x"));
  get.mockResolvedValue({
    data: { changes: [{ entity: "shopping_item", id: "i1", op: "delete", fields: {} }], next_cursor: "c2" },
    error: undefined,
    response: { status: 200 },
  });
  await pull();
  expect(await db.items.get("i1")).toBeUndefined();
});

test("a 410 triggers a full resync from scratch", async () => {
  await db.items.put(item("stale", "old"));
  await db.meta.put({ key: "cursor", value: "expired" });
  get
    .mockResolvedValueOnce({ data: undefined, error: new Error("gone"), response: { status: 410 } })
    .mockResolvedValueOnce({
      data: {
        changes: [
          { entity: "shopping_item", id: "fresh", op: "upsert", fields: { list_id: "l1", label: "new" } },
        ],
        next_cursor: "c3",
      },
      error: undefined,
      response: { status: 200 },
    });
  await pull();
  expect(await db.items.get("stale")).toBeUndefined(); // cache wiped
  expect(await db.items.get("fresh")).toMatchObject({ label: "new" });
});

test("offline edits flush on reconnect (sync = push + pull)", async () => {
  await enqueue("shopping_item", "i1", "upsert", { list_id: "l1", label: "Eier" }, async () => {
    await db.items.put(item("i1", "Eier"));
  });
  expect(await db.outbox.count()).toBe(1); // stayed queued while offline

  post.mockResolvedValue({
    data: {
      applied: [
        {
          entity: "shopping_item",
          id: "i1",
          version: 1,
          deleted: false,
          fields: { list_id: "l1", label: "Eier", checked: false },
        },
      ],
    },
    error: undefined,
    response: { status: 200 },
  });
  get.mockResolvedValue({
    data: { changes: [], next_cursor: null },
    error: undefined,
    response: { status: 200 },
  });
  await sync();
  expect(await db.outbox.count()).toBe(0); // pushed + cleared on reconnect
});

test("pull applies a basic (third sync entity)", async () => {
  get.mockResolvedValue({
    data: {
      changes: [
        { entity: "shopping_basic", id: "b1", op: "upsert", fields: { label: "Butter", category: "Kühlregal" } },
      ],
      next_cursor: "c1",
    },
    error: undefined,
    response: { status: 200 },
  });
  await pull();
  expect(await db.basics.get("b1")).toMatchObject({ label: "Butter", category: "Kühlregal" });
});
