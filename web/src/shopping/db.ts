import Dexie, { type Table } from "dexie";

// Offline store for the shopping list (P3-S3, ARCHITECTURE §8/§10). Mirrors the server: ``lists`` and
// ``items`` are the cached state; ``outbox`` is the queue of local ops not yet acknowledged; ``meta``
// holds the sync cursor. Tombstones are removed locally (server deletes are sticky).

export type LocalList = {
  id: string;
  name: string;
  category_order: string[];
};

export type LocalItem = {
  id: string;
  list_id: string;
  label: string;
  qty: string | null;
  unit: string | null;
  category: string | null;
  checked: boolean;
  source: string;
  notes: string | null;
  reserved_by: string | null;
  checked_by: string | null;
};

export type LocalBasic = {
  id: string;
  label: string;
  category: string | null;
};

export type OutboxOp = {
  seq?: number;
  client_op_id: string;
  entity: "shopping_list" | "shopping_item" | "shopping_basic";
  entity_id: string;
  op: "upsert" | "delete";
  fields: Record<string, unknown>;
  created_at: number;
};

export type Meta = { key: string; value: string | null };

// Local quick-catalog (P3-S5): learned from what the household adds — label → how often + last
// used + its last category. Powers the 1-tap "Schnellkatalog" tiles (T4). Device-local (a convenience,
// not synced).
export type CatalogEntry = {
  label: string;
  category: string | null;
  count: number;
  last_used: number;
};

export class ShoppingDB extends Dexie {
  lists!: Table<LocalList, string>;
  items!: Table<LocalItem, string>;
  outbox!: Table<OutboxOp, number>;
  meta!: Table<Meta, string>;
  catalog!: Table<CatalogEntry, string>;
  basics!: Table<LocalBasic, string>;

  constructor(name = "custode_shopping") {
    super(name);
    this.version(1).stores({
      lists: "id",
      items: "id, list_id",
      outbox: "++seq, created_at",
      meta: "key",
    });
    this.version(2).stores({
      catalog: "label, count, last_used",
    });
    this.version(3).stores({
      basics: "id, label",
    });
  }
}

export const db = new ShoppingDB();

// Logout purge (ADR-0078): household data must not survive the session on a shared device.
// The block flag closes the race with an in-flight pull() — its remaining batches would land
// AFTER the clear below. Any signed-in /v1/auth/me unblocks again (see auth/session.ts), which
// covers every login path.
let writesBlocked = false;

export function shoppingWritesBlocked(): boolean {
  return writesBlocked;
}

export function unblockShoppingWrites(): void {
  writesBlocked = false;
}

// Clears every table — including ones added by future schema versions — atomically.
export async function purgeShoppingCache(): Promise<void> {
  writesBlocked = true;
  await db.transaction("rw", db.tables, async () => {
    await Promise.all(db.tables.map((table) => table.clear()));
  });
}
