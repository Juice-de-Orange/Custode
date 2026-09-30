import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";

vi.mock("../account-deletion/queries", () => ({
  useDeletionBlockers: vi.fn(),
  useDeleteAccount: vi.fn(),
}));

import { useDeleteAccount, useDeletionBlockers } from "../account-deletion/queries";
import { DangerZone } from "../account-deletion/danger-zone";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = (over: object = {}) => ({ mutate: vi.fn(), isPending: false, ...over }) as any;
const query = (over: object = {}) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ({ data: [], isLoading: false, isError: false, isSuccess: true, ...over }) as any;

function renderZone(onDeleted = () => {}) {
  return render(
    <I18nProvider i18n={i18n}>
      <main>
        <DangerZone onDeleted={onDeleted} />
      </main>
    </I18nProvider>,
  );
}

/** Open the disclosure — everything below only exists after this. */
function open() {
  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.open") }));
}

beforeEach(() => {
  vi.mocked(useDeletionBlockers).mockReturnValue(query());
  vi.mocked(useDeleteAccount).mockReturnValue(mutation());
});

afterEach(() => vi.restoreAllMocks());

// --- the blockers are asked before anything is offered ----------------------

test("closed, the blockers are not fetched at all", () => {
  renderZone();
  // The hook is called with enabled=false, so /profile costs no cross-household query.
  expect(vi.mocked(useDeletionBlockers)).toHaveBeenCalledWith(false);
  expect(screen.queryByRole("button", { name: i18n._("deletion.start") })).toBeNull();
});

test("opening asks, and a blocked account never sees the button", () => {
  vi.mocked(useDeletionBlockers).mockReturnValue(
    query({
      data: [{ household_id: "h-1", name: "WG Nord", reason: "last_admin" }],
    }),
  );
  renderZone();
  open();

  expect(vi.mocked(useDeletionBlockers)).toHaveBeenLastCalledWith(true);
  expect(screen.getByText("WG Nord")).toBeTruthy();
  expect(screen.getByText(i18n._("deletion.blocker.lastAdmin"))).toBeTruthy();
  // The point: no invitation to press something that would answer 409.
  expect(screen.queryByRole("button", { name: i18n._("deletion.start") })).toBeNull();
});

test("the two blocking reasons say different things, because one is fixable", () => {
  vi.mocked(useDeletionBlockers).mockReturnValue(
    query({
      data: [
        { household_id: "h-1", name: "WG Nord", reason: "last_admin" },
        { household_id: "h-2", name: "Zuhause", reason: "only_children" },
      ],
    }),
  );
  renderZone();
  open();

  expect(screen.getByText(i18n._("deletion.blocker.lastAdmin"))).toBeTruthy();
  expect(screen.getByText(i18n._("deletion.blocker.onlyChildren"))).toBeTruthy();
});

test("an unknown reason still says something true rather than nothing", () => {
  vi.mocked(useDeletionBlockers).mockReturnValue(
    query({ data: [{ household_id: "h-9", name: "Neu", reason: "something_new" }] }),
  );
  renderZone();
  open();

  expect(screen.getByText(i18n._("deletion.blocker.generic"))).toBeTruthy();
});

test("a query that never ran shows a loading state, not a delete button", () => {
  // The offline case. react-query v5: `isLoading = isPending && isFetching`, and a paused query
  // (fetchStatus "paused") is not fetching — so `isLoading` is false while `data` is undefined.
  // Branching on `isLoading` would let `list = []` mean "no blockers" and offer the button
  // without ever having asked. This is a PWA; offline is a reachable state.
  vi.mocked(useDeletionBlockers).mockReturnValue(
    query({ data: undefined, isLoading: false, isSuccess: false }),
  );
  renderZone();
  open();

  expect(screen.queryByRole("button", { name: i18n._("deletion.start") })).toBeNull();
  expect(screen.getByText(i18n._("state.loading"))).toBeTruthy();
});

// --- the unblocked path takes two deliberate steps --------------------------

test("one click arms, a second deletes — a single click never does", () => {
  const mutate = vi.fn();
  vi.mocked(useDeleteAccount).mockReturnValue(mutation({ mutate }));
  renderZone();
  open();

  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.start") }));
  expect(mutate).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.confirm") }));
  expect(mutate).toHaveBeenCalled();
});

test("cancelling disarms", () => {
  const mutate = vi.fn();
  vi.mocked(useDeleteAccount).mockReturnValue(mutation({ mutate }));
  renderZone();
  open();

  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.start") }));
  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.cancel") }));

  expect(screen.getByRole("button", { name: i18n._("deletion.start") })).toBeTruthy();
  expect(screen.queryByRole("button", { name: i18n._("deletion.confirm") })).toBeNull();
  expect(mutate).not.toHaveBeenCalled();
});

test("the consequences are named before the button, including the immediate exit", () => {
  renderZone();
  open();

  expect(screen.getByText(i18n._("deletion.consequence.households"))).toBeTruthy();
  expect(screen.getByText(i18n._("deletion.consequence.economy"))).toBeTruthy();
  expect(screen.getByText(i18n._("deletion.consequence.grace"))).toBeTruthy();
  expect(screen.getByText(i18n._("deletion.consequence.final"))).toBeTruthy();
});

test("success hands control back so the caller can leave the page", () => {
  const onDeleted = vi.fn();
  vi.mocked(useDeleteAccount).mockReturnValue(
    mutation({
      mutate: (_v: unknown, opts: { onSuccess: () => void }) => opts.onSuccess(),
    }),
  );
  renderZone(onDeleted);
  open();
  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.start") }));
  fireEvent.click(screen.getByRole("button", { name: i18n._("deletion.confirm") }));

  expect(onDeleted).toHaveBeenCalled();
});

// --- accessibility ----------------------------------------------------------

test("the opened danger zone has no axe violations", async () => {
  const { container } = renderZone();
  open();
  expect(await axe(container)).toHaveNoViolations();
});
