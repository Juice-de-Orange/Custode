import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";
import { messages as de } from "../i18n/locales/de";
import { messages as en } from "../i18n/locales/en";
import { BRAND_NAME } from "../lib/brand";
import { ProblemError } from "../lib/problem";

vi.mock("../export/queries", async () => {
  const actual = await vi.importActual<typeof import("../export/queries")>("../export/queries");
  // Only the hook is faked — the file-name parsing below is the real implementation.
  return { ...actual, useExportDownload: vi.fn() };
});

import { fallbackFilename, filenameFromDisposition, useExportDownload } from "../export/queries";
import { ExportSection } from "../export/export-section";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = (over: object = {}) => ({ mutate: vi.fn(), isPending: false, ...over }) as any;

function renderSection(isAdmin = false) {
  return render(
    <I18nProvider i18n={i18n}>
      <main>
        <ExportSection isAdmin={isAdmin} />
      </main>
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useExportDownload).mockReturnValue(mutation());
});

// --- who may ask for what ---------------------------------------------------

test("every role can export their own data; only an admin sees the household export", () => {
  const { unmount } = renderSection(false);
  expect(screen.getByText(i18n._("export.me"))).toBeTruthy();
  expect(screen.queryByText(i18n._("export.household"))).toBeNull();
  unmount();

  renderSection(true);
  expect(screen.getByText(i18n._("export.me"))).toBeTruthy();
  expect(screen.getByText(i18n._("export.household"))).toBeTruthy();
});

test("the buttons ask for the scope they name", () => {
  const mutate = vi.fn();
  vi.mocked(useExportDownload).mockReturnValue(mutation({ mutate }));
  renderSection(true);

  fireEvent.click(screen.getByText(i18n._("export.me")));
  expect(mutate.mock.calls[0][0]).toBe("me");

  fireEvent.click(screen.getByText(i18n._("export.household")));
  expect(mutate.mock.calls[1][0]).toBe("household");
});

// --- the promises the section makes -----------------------------------------

test("the section names what is withheld, not only what is included", () => {
  const { container } = renderSection();
  // Pins the honesty requirement: an export UI that advertises only completeness misleads.
  // These four groups are exactly the ones the backend redacts (app/export_policy.py _REDACT).
  expect(container.textContent).toContain("Passwörter");
  expect(container.textContent).toContain("Sitzungsgeheimnisse");
  expect(container.textContent).toContain("CalDAV");
  expect(container.textContent).toContain("Tresor");
  // …and it says the vault CONTENT does travel, encrypted — the key is what stays behind.
  expect(i18n._("export.contains.body")).toContain("verschlüsselt");
});

test("the household hint states that member health data stays out", () => {
  renderSection(true);
  // ADR-0081 / N-2: member-scoped RLS keeps Art.-9 rows away from an exporting admin. The UI
  // must not imply the archive is everything about everyone.
  expect(screen.getByText(i18n._("export.householdHint"))).toBeTruthy();
});

test("the brand name comes from the constant, never from the catalog", () => {
  const { container } = renderSection();
  // Both catalogs carry a {brand} placeholder; a rename must not need a translation change
  // (CLAUDE.md: the marketing name is rendered from BRAND_NAME, never hardcoded).
  expect(de["export.intro"]).toContain("{brand}");
  expect(en["export.intro"]).toContain("{brand}");
  expect(container.textContent).toContain(BRAND_NAME);
});

// --- the trio ---------------------------------------------------------------

test("before anything happened the empty state explains what to expect", () => {
  renderSection();
  expect(screen.getByText(i18n._("export.empty"))).toBeTruthy();
});

test("a running export is announced as a wait, and blocks a second run", () => {
  vi.mocked(useExportDownload).mockReturnValue(mutation({ isPending: true, variables: "me" }));
  renderSection(true);

  const status = screen.getByRole("status");
  expect(status.textContent).toContain(i18n._("export.preparing"));
  // Only the running button changes its label; both are disabled — building two archives at once
  // is the most expensive thing a member could ask of the server, and never intended.
  expect(screen.getByText(i18n._("export.pending")).closest("button")?.disabled).toBe(true);
  expect(screen.getByText(i18n._("export.household")).closest("button")?.disabled).toBe(true);
});

test("a finished export names the file it saved", () => {
  vi.mocked(useExportDownload).mockReturnValue(
    mutation({
      mutate: (_scope: string, opts: { onSuccess: (name: string) => void }) =>
        opts.onSuccess("custode-export-personal-2026-07-31.zip"),
    }),
  );
  renderSection();
  fireEvent.click(screen.getByText(i18n._("export.me")));

  const status = screen.getByRole("status");
  expect(status.textContent).toContain("custode-export-personal-2026-07-31.zip");
  expect(screen.queryByText(i18n._("export.empty"))).toBeNull();
});

test("a too-large archive is explained as an operator handover, with its reference code", () => {
  vi.mocked(useExportDownload).mockReturnValue(
    mutation({
      mutate: (_scope: string, opts: { onError: (e: unknown) => void }) =>
        opts.onError(new ProblemError("export_too_large", "CUS-7Q2F-9K")),
    }),
  );
  renderSection();
  fireEvent.click(screen.getByText(i18n._("export.me")));

  const alert = screen.getByRole("alert");
  expect(alert.textContent).toContain(i18n._("export.err.tooLarge"));
  expect(alert.textContent).toContain("CUS-7Q2F-9K");
});

test("a 403 on the household export reads as information, not as a scolding", () => {
  vi.mocked(useExportDownload).mockReturnValue(
    mutation({
      mutate: (_scope: string, opts: { onError: (e: unknown) => void }) =>
        opts.onError(new ProblemError("forbidden")),
    }),
  );
  renderSection(true);
  fireEvent.click(screen.getByText(i18n._("export.household")));
  expect(screen.getByRole("alert").textContent).toContain(i18n._("export.err.forbidden"));
});

test("an unknown slug still gets a human message", () => {
  vi.mocked(useExportDownload).mockReturnValue(
    mutation({
      mutate: (_scope: string, opts: { onError: (e: unknown) => void }) =>
        opts.onError(new ProblemError("brand_new")),
    }),
  );
  renderSection();
  fireEvent.click(screen.getByText(i18n._("export.me")));
  expect(screen.getByRole("alert").textContent).toContain(i18n._("export.err.generic"));
});

// --- a11y -------------------------------------------------------------------

test("the section has no axe violations (idle and running)", async () => {
  const { container, unmount } = renderSection(true);
  expect(await axe(container)).toHaveNoViolations();
  unmount();

  vi.mocked(useExportDownload).mockReturnValue(mutation({ isPending: true, variables: "me" }));
  const running = renderSection(true);
  expect(await axe(running.container)).toHaveNoViolations();
});

// --- the file name the browser is handed ------------------------------------

test("the server's Content-Disposition decides the file name", () => {
  const header = 'attachment; filename="custode-export-personal-2026-07-31.zip"';
  expect(filenameFromDisposition(header, "fallback.zip")).toBe(
    "custode-export-personal-2026-07-31.zip",
  );
  expect(filenameFromDisposition("attachment; filename=plain.zip", "fallback.zip")).toBe(
    "plain.zip",
  );
  expect(
    filenameFromDisposition("attachment; filename*=UTF-8''export%20%C3%A4.zip", "fallback.zip"),
  ).toBe("export ä.zip");
});

test("a header that tries to escape the download folder cannot", () => {
  // Server-generated today; this pins the guard for the next route that writes the header. The
  // cost of being wrong lands on the person who clicked, not on us.
  expect(filenameFromDisposition('attachment; filename="../../etc/passwd"', "fb.zip")).toBe(
    "passwd",
  );
  expect(filenameFromDisposition('attachment; filename="..\\\\..\\\\evil.zip"', "fb.zip")).toBe(
    "evil.zip",
  );
  expect(filenameFromDisposition('attachment; filename=".."', "fb.zip")).toBe("fb.zip");
  expect(filenameFromDisposition("", "fb.zip")).toBe("fb.zip");
  expect(filenameFromDisposition(null, "fb.zip")).toBe("fb.zip");
});

test("without a usable header the name still says what the file is", () => {
  const day = new Date("2026-07-31T10:00:00Z");
  expect(fallbackFilename("me", day)).toBe("custode-export-personal-2026-07-31.zip");
  expect(fallbackFilename("household", day)).toBe("custode-export-household-2026-07-31.zip");
});
