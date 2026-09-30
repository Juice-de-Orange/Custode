import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";

vi.mock("../household/queries", () => ({
  useDissolvePreview: vi.fn(),
  useDissolveHousehold: vi.fn(),
}));

import { useDissolveHousehold, useDissolvePreview } from "../household/queries";
import { DissolveSection } from "../household/dissolve-section";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = (over: object = {}) => ({ mutate: vi.fn(), isPending: false, ...over }) as any;
const query = (over: object = {}) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ({ isLoading: false, isError: false, isSuccess: true, ...over }) as any;

const PREVIEW = { household_name: "WG Nord", member_count: 3, child_account_count: 1 };

function renderSection(onDissolved = () => {}) {
  return render(
    <I18nProvider i18n={i18n}>
      <main>
        <DissolveSection onDissolved={onDissolved} />
      </main>
    </I18nProvider>,
  );
}

function open() {
  fireEvent.click(screen.getByRole("button", { name: i18n._("dissolve.open") }));
}

beforeEach(() => {
  vi.mocked(useDissolvePreview).mockReturnValue(query({ data: PREVIEW }));
  vi.mocked(useDissolveHousehold).mockReturnValue(mutation());
});

afterEach(() => vi.restoreAllMocks());

// --- die Vorschau steht vor dem Knopf ------------------------------------------------------------

test("closed, nothing is fetched — /account is every session's landing page", () => {
  renderSection();
  expect(vi.mocked(useDissolvePreview)).toHaveBeenCalledWith(false);
  expect(screen.queryByRole("button", { name: i18n._("dissolve.confirm") })).toBeNull();
});

test("opening shows who it hits, before anything can be pressed", () => {
  renderSection();
  open();
  expect(vi.mocked(useDissolvePreview)).toHaveBeenLastCalledWith(true);
  expect(screen.getByText(/3 Personen verlieren/)).toBeTruthy();
  expect(screen.getByText(/1 Kinder-Konto wird mitgelöscht/)).toBeTruthy();
});

test("a household without children does not claim any are deleted", () => {
  vi.mocked(useDissolvePreview).mockReturnValue(
    query({ data: { ...PREVIEW, child_account_count: 0 } }),
  );
  renderSection();
  open();
  expect(screen.queryByText(/Kinder-Konto/)).toBeNull();
});

test("the consequence that surprises is spelled out: there is no undo within the 30 days", () => {
  renderSection();
  open();
  expect(screen.getByText(i18n._("dissolve.consequence.final"))).toBeTruthy();
});

test("a preview that never ran shows a loading state, not a button", () => {
  // Offline ist `isLoading` false, während `data` undefined ist — der Name, gegen den bestätigt
  // wird, käme dann als leerer String, und ein leeres Feld würde „passen".
  vi.mocked(useDissolvePreview).mockReturnValue(
    query({ data: undefined, isSuccess: false }),
  );
  renderSection();
  open();
  expect(screen.queryByRole("button", { name: i18n._("dissolve.confirm") })).toBeNull();
  expect(screen.getByText(i18n._("state.loading"))).toBeTruthy();
});

// --- der abgetippte Name ist die Bestätigung -----------------------------------------------------

test("the button stays disabled until the household name matches exactly", () => {
  const mutate = vi.fn();
  vi.mocked(useDissolveHousehold).mockReturnValue(mutation({ mutate }));
  renderSection();
  open();

  const confirm = screen.getByRole("button", { name: i18n._("dissolve.confirm") });
  expect(confirm).toHaveProperty("disabled", true);

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "WG Nor" } });
  expect(confirm).toHaveProperty("disabled", true);

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "WG Nord" } });
  expect(confirm).toHaveProperty("disabled", false);

  fireEvent.click(confirm);
  expect(mutate).toHaveBeenCalledWith("WG Nord", expect.anything());
});

test("an empty field never counts as a match", () => {
  // Sonst genügte ein Klick auf einem Haushalt ohne Namen — und `expected` ist leer, solange die
  // Vorschau nicht da ist.
  const mutate = vi.fn();
  vi.mocked(useDissolveHousehold).mockReturnValue(mutation({ mutate }));
  vi.mocked(useDissolvePreview).mockReturnValue(
    query({ data: { ...PREVIEW, household_name: "" } }),
  );
  renderSection();
  open();

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
  expect(
    screen.getByRole("button", { name: i18n._("dissolve.confirm") }),
  ).toHaveProperty("disabled", true);
  expect(mutate).not.toHaveBeenCalled();
});

test("success hands control back so the caller can leave the page", () => {
  const onDissolved = vi.fn();
  vi.mocked(useDissolveHousehold).mockReturnValue(
    mutation({
      mutate: (_v: unknown, opts: { onSuccess: () => void }) => opts.onSuccess(),
    }),
  );
  renderSection(onDissolved);
  open();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "WG Nord" } });
  fireEvent.click(screen.getByRole("button", { name: i18n._("dissolve.confirm") }));
  expect(onDissolved).toHaveBeenCalled();
});

test("the opened section has no axe violations", async () => {
  const { container } = renderSection();
  open();
  expect(await axe(container)).toHaveNoViolations();
});
