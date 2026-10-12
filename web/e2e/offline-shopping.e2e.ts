import { expect, type Page, test } from "@playwright/test";

// The README promise "one shared shopping list that works offline in the shop", end to end in a
// real browser: the production build with its service worker, Dexie and the sync outbox against a
// running api. Items are added and checked off offline, survive a reload while still offline
// (the app shell comes from the service worker, the list from Dexie), and reach the server once
// the connection is back.

type SyncChange = { entity: string; id: string; op: string; fields: Record<string, unknown> };

async function registerWithHousehold(page: Page): Promise<void> {
  const suffix = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  await page.goto("/register");
  await page.locator("#reg-name").fill("Offline Tester");
  await page.locator("#reg-email").fill(`offline-${suffix}@example.com`);
  await page.locator("#reg-password").fill("offline-test-password");
  await page.locator("#reg-password-confirm").fill("offline-test-password");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.locator("#hh-name").fill("Offline household");
  const created = page.waitForResponse(
    (res) => res.url().endsWith("/v1/households") && res.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create household" }).click();
  expect((await created).ok()).toBeTruthy();
}

// Server state as the sync endpoint sees it (GET, so no CSRF token is needed); the request shares
// the browser context's session cookies.
async function serverItems(page: Page): Promise<Map<string, boolean>> {
  const res = await page.request.get("/v1/sync/shopping?limit=200");
  expect(res.ok()).toBeTruthy();
  const body = (await res.json()) as { changes: SyncChange[] };
  const items = new Map<string, boolean>();
  for (const change of body.changes) {
    if (change.entity === "shopping_item" && change.op !== "delete") {
      items.set(String(change.fields.label), Boolean(change.fields.checked));
    }
  }
  return items;
}

function row(page: Page, label: string) {
  return page.getByRole("listitem").filter({ hasText: label });
}

test("shopping list: add and check off offline, reload offline, sync when back online", async ({
  page,
  context,
}) => {
  await registerWithHousehold(page);

  // A new household starts without a list; create the first one while online.
  await page.goto("/shopping");
  await page.getByRole("textbox", { name: "List name" }).fill("Weekly shop");
  await page.getByRole("button", { name: "Create list" }).click();
  await expect(page.getByRole("combobox", { name: "Select list" })).toHaveValue(/.+/);
  const addItem = page.getByRole("textbox", { name: "Add item" });
  await expect(addItem).toBeVisible();
  // The page must be controlled by the service worker before the network goes away, or an
  // offline reload has nothing to serve the app shell from. The first visit installs it; the
  // reload puts the page under its control.
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Select list" })).toHaveValue(/.+/);
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

  await context.setOffline(true);

  await addItem.fill("Oat milk");
  await addItem.press("Enter");
  await addItem.fill("Apples");
  await addItem.press("Enter");
  await expect(row(page, "Oat milk")).toBeVisible();
  await expect(row(page, "Apples")).toBeVisible();
  // click(), not check(): the box is controlled and flips once Dexie has the change (the row
  // then moves to "Done"), which check() reports as "did not change its state".
  await row(page, "Apples").getByRole("checkbox").click();
  await expect(row(page, "Apples").getByRole("checkbox")).toBeChecked();

  // Reopen the app in the shop, still without a connection.
  await page.reload();
  await expect(row(page, "Oat milk")).toBeVisible();
  await expect(row(page, "Oat milk").getByRole("checkbox")).not.toBeChecked();
  await expect(row(page, "Apples").getByRole("checkbox")).toBeChecked();

  await context.setOffline(false);

  await expect
    .poll(async () => Object.fromEntries(await serverItems(page)), { timeout: 30_000 })
    .toEqual({ "Oat milk": false, Apples: true });
});
