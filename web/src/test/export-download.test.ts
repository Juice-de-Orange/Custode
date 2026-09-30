import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { client } from "../api/client.gen";
import { downloadExport } from "../export/queries";
import { ProblemError } from "../lib/problem";

// Exercises the real request path: the ZIP route answers ``application/zip``, so the generated
// client must be asked for a blob and its errors must still arrive as RFC-9457 problems. The
// section test mocks the hook, so without this file nothing would cover the mechanism.

// The client builds relative URLs; jsdom brings no Request, so Node's needs an absolute base.
const BASE = "https://app.example";

let objectUrls: string[] = [];
let clicked: HTMLAnchorElement[] = [];

function zip(headers: Record<string, string> = {}): Response {
  return new Response("PK", {
    status: 200,
    headers: { "Content-Type": "application/zip", ...headers },
  });
}

/** The client always calls ``fetch`` with a built ``Request``, never a bare URL string. */
type FetchFn = (request: Request) => Promise<Response>;

function requestedPath(request: Request): string {
  return new URL(request.url).pathname;
}

function problem(status: number, slug: string): Response {
  return new Response(
    JSON.stringify({ type: `https://custode.example/problems/${slug}`, reference: "CUS-1" }),
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

beforeEach(() => {
  objectUrls = [];
  clicked = [];
  client.setConfig({ baseUrl: BASE });
  URL.createObjectURL = vi.fn(() => {
    const url = `blob:mock-${objectUrls.length}`;
    objectUrls.push(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  client.setConfig({ baseUrl: undefined });
});

test("asks the right route and saves the file the server named", async () => {
  const fetchMock = vi.fn<FetchFn>(async () =>
    zip({ "Content-Disposition": 'attachment; filename="custode-export-personal-2026-07-31.zip"' }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const name = await downloadExport("me");

  expect(requestedPath(fetchMock.mock.calls[0][0])).toBe("/v1/me/export");
  expect(name).toBe("custode-export-personal-2026-07-31.zip");
  // The archive reached the browser as a download, not as a rendered page.
  expect(clicked[0].download).toBe("custode-export-personal-2026-07-31.zip");
  expect(clicked[0].href).toBe(objectUrls[0]);
  expect(clicked[0].isConnected).toBe(false); // the anchor is removed again
});

test("the household export is a different route, not a parameter", async () => {
  const fetchMock = vi.fn<FetchFn>(async () => zip());
  vi.stubGlobal("fetch", fetchMock);

  await downloadExport("household");

  expect(requestedPath(fetchMock.mock.calls[0][0])).toBe("/v1/household/export");
});

test("the object URL is released again", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(async () => zip()));
  try {
    await downloadExport("me");
    expect(URL.revokeObjectURL).not.toHaveBeenCalled(); // not in the same task — Safari aborts
    vi.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(objectUrls[0]);
  } finally {
    vi.useRealTimers();
  }
});

test("a problem response still arrives as a ProblemError, not as a blob", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => problem(413, "export_too_large")));

  await expect(downloadExport("me")).rejects.toBeInstanceOf(ProblemError);
  await expect(downloadExport("me")).rejects.toMatchObject({
    slug: "export_too_large",
    reference: "CUS-1",
  });
  // Nothing was handed to the browser: a failed export must not save an error page as a .zip.
  expect(clicked).toHaveLength(0);
});

test("a 403 on the household route surfaces as forbidden", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => problem(403, "forbidden")));
  await expect(downloadExport("household")).rejects.toMatchObject({ slug: "forbidden" });
});
