import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { client } from "../api/client.gen";
import { postRegister, saveAccountLocale } from "../auth/session";
import { setLocalePref } from "../lib/locale";

// The backend writes e-mails (verification, password reset, weekly digest) in the account's
// language (`users.locale`). The interface language is chosen per browser, so these two requests
// are what carries it to the account: at registration, and when the person changes it later.

const BASE = "https://app.example";

type FetchFn = (request: Request) => Promise<Response>;

function json(body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

beforeEach(() => client.setConfig({ baseUrl: BASE }));

afterEach(() => {
  setLocalePref(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  client.setConfig({ baseUrl: undefined });
});

test("registration sends the interface language as the account locale", async () => {
  setLocalePref("en");
  const fetchMock = vi.fn<FetchFn>(async () => json({ user_id: "u1" }));
  vi.stubGlobal("fetch", fetchMock);

  await postRegister({ email: "a@example.com", password: "long-enough-pw", display_name: "A" });

  const request = fetchMock.mock.calls[0][0];
  expect(new URL(request.url).pathname).toBe("/v1/auth/register");
  expect(await request.json()).toMatchObject({ email: "a@example.com", locale: "en" });
});

test("registration follows the browser language when nothing is pinned", async () => {
  const fetchMock = vi.fn<FetchFn>(async () => json({ user_id: "u1" }));
  vi.stubGlobal("fetch", fetchMock);

  await postRegister({ email: "a@example.com", password: "long-enough-pw", display_name: "A" });

  // test/setup.ts gives the suite a German browser.
  expect(await fetchMock.mock.calls[0][0].json()).toMatchObject({ locale: "de" });
});

test("a language change is saved to the account with the current ETag", async () => {
  const fetchMock = vi.fn<FetchFn>(async (request) =>
    request.method === "GET"
      ? json({ display_name: "A", locale: "de", version: 3 }, { ETag: '"3"' })
      : json({ display_name: "A", locale: "en", version: 4 }, { ETag: '"4"' }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await saveAccountLocale("en");

  const [get, patch] = fetchMock.mock.calls.map(([request]) => request);
  expect(get.method).toBe("GET");
  expect(new URL(get.url).pathname).toBe("/v1/account/profile");
  expect(patch.method).toBe("PATCH");
  expect(new URL(patch.url).pathname).toBe("/v1/account/profile");
  expect(patch.headers.get("If-Match")).toBe('"3"');
  expect(await patch.json()).toEqual({ locale: "en" });
});

test("saving the language never throws — the interface switch must not depend on it", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<FetchFn>(async () => new Response("", { status: 503 })),
  );
  await expect(saveAccountLocale("en")).resolves.toBeUndefined();
});
