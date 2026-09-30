import { expect, test } from "vitest";

import { db, purgeShoppingCache, shoppingWritesBlocked, unblockShoppingWrites } from "../shopping/db";
import { enqueue } from "../shopping/sync";

// Logout privacy guarantee (ADR-0078): on a shared device no household data may survive the
// session — every Dexie table must be empty after the purge (fake-indexeddb via test setup),
// and sync writes stay blocked so an in-flight pull cannot repopulate the cache.
test("purgeShoppingCache clears every table", async () => {
  await db.lists.put({ id: "l1", name: "Wocheneinkauf", category_order: [] });
  await db.items.put({
    id: "i1",
    list_id: "l1",
    label: "Milch",
    qty: null,
    unit: null,
    category: null,
    checked: false,
    source: "manual",
    notes: null,
    reserved_by: null,
    checked_by: null,
  });
  await db.outbox.add({
    client_op_id: "op1",
    entity: "shopping_item",
    entity_id: "i1",
    op: "upsert",
    fields: { label: "Milch" },
    created_at: 1,
  });
  await db.meta.put({ key: "cursor", value: "42" });
  await db.catalog.put({ label: "Milch", category: null, count: 3, last_used: 1 });
  await db.basics.put({ id: "b1", label: "Brot", category: null });

  await purgeShoppingCache();

  for (const table of db.tables) {
    expect(await table.count(), `table ${table.name} not purged`).toBe(0);
  }

  // Sync writes are blocked after the purge: an enqueue (and by the same flag every pull
  // batch) must be a no-op until a signed-in session unblocks again.
  expect(shoppingWritesBlocked()).toBe(true);
  await enqueue("shopping_item", "i2", "upsert", { label: "Butter" }, async () => {
    await db.items.put({
      id: "i2",
      list_id: "l1",
      label: "Butter",
      qty: null,
      unit: null,
      category: null,
      checked: false,
      source: "manual",
      notes: null,
      reserved_by: null,
      checked_by: null,
    });
  });
  expect(await db.items.count()).toBe(0);
  expect(await db.outbox.count()).toBe(0);

  unblockShoppingWrites();
  expect(shoppingWritesBlocked()).toBe(false);
});
