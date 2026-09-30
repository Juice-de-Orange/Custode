import { client } from "../api/client.gen";
import { db, shoppingWritesBlocked, type LocalItem, type LocalList, type OutboxOp } from "./db";

// Offline sync engine for the shopping list (P3-S3). Mirrors the server's Sync-Batch semantics:
// local writes are optimistic + queued (outbox), pushed when online; the server's authoritative state
// overwrites the cache; a delta pull keeps the cache fresh. The same idempotency keys (client_op_id)
// make replays safe. Conceptually identical to the planned Android (Room) client.

const LIMIT = 200;

type WireFields = Record<string, unknown>;
type ServerEntityState = {
  entity: string;
  id: string;
  version: number;
  deleted: boolean;
  fields: WireFields;
};
type SyncChange = { entity: string; id: string; op: "upsert" | "delete"; fields: WireFields };

function newId(): string {
  return crypto.randomUUID();
}

function asStr(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}

async function applyEntity(
  entity: string,
  id: string,
  deleted: boolean,
  fields: WireFields,
): Promise<void> {
  if (entity === "shopping_list") {
    if (deleted) {
      await db.lists.delete(id);
      return;
    }
    const list: LocalList = {
      id,
      name: String(fields.name ?? ""),
      category_order: (fields.category_order as string[] | undefined) ?? [],
    };
    await db.lists.put(list);
    return;
  }
  if (entity === "shopping_basic") {
    if (deleted) {
      await db.basics.delete(id);
      return;
    }
    await db.basics.put({ id, label: String(fields.label ?? ""), category: asStr(fields.category) });
    return;
  }
  if (deleted) {
    await db.items.delete(id);
    return;
  }
  const item: LocalItem = {
    id,
    list_id: String(fields.list_id ?? ""),
    label: String(fields.label ?? ""),
    qty: asStr(fields.qty),
    unit: asStr(fields.unit),
    category: asStr(fields.category),
    checked: Boolean(fields.checked),
    source: String(fields.source ?? "manual"),
    notes: asStr(fields.notes),
    reserved_by: asStr(fields.reserved_by),
    checked_by: asStr(fields.checked_by),
  };
  await db.items.put(item);
}

// Apply a local change immediately (optimistic) + queue it for the server; kicks off a best-effort
// sync (a no-op enqueue offline just leaves the op in the outbox).
export async function enqueue(
  entity: OutboxOp["entity"],
  entityId: string,
  op: OutboxOp["op"],
  fields: WireFields,
  optimistic: () => Promise<void>,
): Promise<void> {
  if (shoppingWritesBlocked()) return; // logged out (purge ran) — nothing may be written
  await db.transaction("rw", db.lists, db.items, db.outbox, db.basics, async () => {
    await optimistic();
    await db.outbox.add({
      client_op_id: newId(),
      entity,
      entity_id: entityId,
      op,
      fields,
      created_at: Date.now(),
    });
  });
  void sync().catch(() => undefined);
}

// Push queued ops; the server's authoritative state overwrites the local cache, then the queue clears.
export async function push(): Promise<void> {
  if (shoppingWritesBlocked()) return;
  const ops = await db.outbox.orderBy("created_at").toArray();
  if (ops.length === 0) return;
  const { data, error, response } = await client.post({
    url: "/v1/sync/shopping/batch",
    body: {
      ops: ops.map((o) => ({
        client_op_id: o.client_op_id,
        entity: o.entity,
        id: o.entity_id,
        base_version: 0,
        op: o.op,
        fields: o.fields,
      })),
    },
  });
  if (error) {
    if (response) throw new Error(`sync push rejected: ${response.status}`);
    return; // network error (offline) — keep the queue, retry on the next sync
  }
  const applied = (data as { applied: ServerEntityState[] }).applied;
  await db.transaction("rw", db.lists, db.items, db.outbox, db.basics, async () => {
    for (const state of applied) {
      await applyEntity(state.entity, state.id, state.deleted, state.fields);
    }
    await db.outbox.bulkDelete(ops.map((o) => o.seq as number));
  });
}

// Pull server changes since the stored cursor into the cache. A 410 triggers a full resync.
export async function pull(): Promise<void> {
  let cursor = (await db.meta.get("cursor"))?.value ?? null;
  for (;;) {
    if (shoppingWritesBlocked()) return; // logout purge ran — stop repopulating the cache
    const url = cursor
      ? `/v1/sync/shopping?cursor=${encodeURIComponent(cursor)}&limit=${LIMIT}`
      : `/v1/sync/shopping?limit=${LIMIT}`;
    const { data, error, response } = await client.get({ url });
    if (error) {
      if (response?.status === 410) await resync();
      return; // offline/transient — retry later
    }
    const res = data as { changes: SyncChange[]; next_cursor: string | null };
    await db.transaction("rw", db.lists, db.items, db.basics, async () => {
      for (const ch of res.changes) {
        await applyEntity(ch.entity, ch.id, ch.op === "delete", ch.fields);
      }
    });
    cursor = res.next_cursor;
    await db.meta.put({ key: "cursor", value: cursor });
    if (res.changes.length < LIMIT) break;
  }
}

// The server says our cursor is too old (past the 90-day tombstone window): drop the cache + cursor
// and pull from scratch.
export async function resync(): Promise<void> {
  if (shoppingWritesBlocked()) return;
  await db.transaction("rw", db.lists, db.items, db.basics, db.meta, async () => {
    await db.lists.clear();
    await db.items.clear();
    await db.basics.clear();
    await db.meta.delete("cursor");
  });
  await pull();
}

export async function sync(): Promise<void> {
  await push();
  await pull();
}
