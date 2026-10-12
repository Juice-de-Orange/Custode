import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { ImprintPage, PrivacyPage } from "../routes/legal";

// Imprint and privacy policy belong to whoever runs the instance (bar 8, legally relevant). They
// used to be draft wording in the UI catalog — "provider details will be added before the public
// launch", "the service runs in the EU" — which every instance shipped as if it were its own.
// Now the operator provides Markdown files under /legal/ (docs/operations.md, "Legal pages");
// without them the page says so instead of showing a text that looks like a real imprint.

type Files = Record<string, { body: string; type?: string; status?: number }>;
let files: Files = {};
let requested: string[] = [];

beforeEach(() => {
  files = {};
  requested = [];
  i18n.activate("de");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requested.push(url);
      const f = files[url];
      if (!f) return new Response("not found", { status: 404 });
      return new Response(f.body, {
        status: f.status ?? 200,
        headers: { "content-type": f.type ?? "text/markdown; charset=utf-8" },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function show(page: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider i18n={i18n}>{page}</I18nProvider>
    </QueryClientProvider>,
  );
}

test("without operator files both pages say so and show no placeholder legal text", async () => {
  show(<ImprintPage />);
  expect(await screen.findByText(/hat noch kein Impressum hinterlegt/)).toBeInTheDocument();
  expect(requested).toEqual(["/legal/imprint.de.md", "/legal/imprint.md"]);
  expect(document.body).not.toHaveTextContent(/öffentlichen Start|in der EU|Entwurf/);
});

test("an SPA fallback (index.html with 200) counts as 'not provided', not as the imprint", async () => {
  files["/legal/privacy.md"] = { body: "<!doctype html><html></html>", type: "text/html" };
  show(<PrivacyPage />);
  expect(
    await screen.findByText(/hat noch keine Datenschutzerklärung hinterlegt/),
  ).toBeInTheDocument();
});

test("the operator's Markdown is rendered; the language file wins over the generic one", async () => {
  files["/legal/imprint.md"] = { body: "# Generic" };
  files["/legal/imprint.de.md"] = {
    body: "## Anbieter\nErika Muster\nBeispielweg 1\n\n- **E-Mail:** [mail](mailto:erika@example.org)\n- [Bad](javascript:alert(1))\n\n<script>alert(1)</script>",
  };
  const { container } = show(<ImprintPage />);
  expect(await screen.findByRole("heading", { name: "Anbieter" })).toBeInTheDocument();
  expect(screen.queryByText("Generic")).toBeNull();
  // A single line break stays one (addresses).
  expect(container.querySelector("p br")).not.toBeNull();
  expect(screen.getByRole("link", { name: "mail" })).toHaveAttribute("href", "mailto:erika@example.org");
  // No unsafe link and no markup from the file: both stay plain text.
  expect(screen.queryByRole("link", { name: "Bad" })).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect(container).toHaveTextContent("<script>alert(1)</script>");
});

test("a network failure shows an error, not 'not provided'", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("offline");
    }),
  );
  show(<PrivacyPage />);
  expect(await screen.findByText("Etwas ist schiefgelaufen.")).toBeInTheDocument();
  expect(screen.queryByText(/nicht hinterlegt|noch keine/)).toBeNull();
});
