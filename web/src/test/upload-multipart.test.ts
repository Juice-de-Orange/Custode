// @vitest-environment node
//
// Node, not jsdom: the assertion is about what leaves the browser, and that needs a `Request`
// and a `FormData` from the same implementation. Under jsdom the two come from different worlds
// (jsdom's FormData, Node's Request) and the body would be the string "[object FormData]" — a
// test that could not tell a working upload from a broken one.

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { client } from "../api/client.gen";
import { uploadAttachment } from "../guides/queries";
import { putPhoto } from "../recipes/queries";

// Regression for BUGLOG 2026-10-03: both uploads handed a FormData to the generated client
// without a body serializer. The client's default is JSON.stringify — a FormData stringifies to
// "{}" — so every upload left the PWA as `Content-Type: application/json` with an empty object
// and came back 422. The backend tests post real multipart and never saw it.

let sent: Request[] = [];

beforeEach(() => {
  sent = [];
  // Node's Request needs an absolute URL; the browser resolves the relative one against the page.
  client.setConfig({ baseUrl: "http://localhost" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      sent.push(request);
      return new Response(JSON.stringify({ id: "x" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function expectMultipartFile(request: Request, name: string, content: string) {
  // The boundary is part of the header, so it must come from the runtime, not from a default.
  expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data; boundary=/);
  const form = await request.formData();
  const file = form.get("file");
  expect(file).toBeInstanceOf(File);
  expect((file as File).name).toBe(name);
  expect(await (file as File).text()).toBe(content);
}

test("a guide attachment leaves as multipart/form-data with the file in it", async () => {
  const file = new File(["%PDF-1.4 test"], "anleitung.pdf", { type: "application/pdf" });
  await uploadAttachment({ guideId: "g1", file });
  expect(sent).toHaveLength(1);
  expect(sent[0].method).toBe("POST");
  expect(new URL(sent[0].url).pathname).toBe("/v1/guides/g1/attachments");
  await expectMultipartFile(sent[0], "anleitung.pdf", "%PDF-1.4 test");
});

test("a recipe photo leaves as multipart/form-data with the file in it", async () => {
  const file = new File(["fake-jpeg-bytes"], "foto.jpg", { type: "image/jpeg" });
  await putPhoto({ id: "r1", file });
  expect(sent).toHaveLength(1);
  expect(sent[0].method).toBe("PUT");
  expect(new URL(sent[0].url).pathname).toBe("/v1/recipes/r1/photo");
  await expectMultipartFile(sent[0], "foto.jpg", "fake-jpeg-bytes");
});
