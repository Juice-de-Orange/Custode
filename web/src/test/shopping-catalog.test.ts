import { beforeEach, expect, test } from "vitest";

import { db } from "../shopping/db";
import { recordCatalog } from "../shopping/queries";

beforeEach(async () => {
  await db.catalog.clear();
});

test("recordCatalog counts uses and keeps the first known category", async () => {
  await recordCatalog("Milch", "Kühlregal");
  await recordCatalog("Milch", null); // a later add without a category keeps the known one
  const entry = await db.catalog.get("Milch");
  expect(entry?.count).toBe(2);
  expect(entry?.category).toBe("Kühlregal");
});

test("catalog ranks most-used first", async () => {
  await recordCatalog("Brot", null);
  await recordCatalog("Eier", null);
  await recordCatalog("Eier", null);
  const top = await db.catalog.orderBy("count").reverse().toArray();
  expect(top[0]?.label).toBe("Eier");
});
