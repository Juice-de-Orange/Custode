import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

vi.mock("../wearables/queries", async () => {
  const actual = await vi.importActual<typeof import("../wearables/queries")>(
    "../wearables/queries",
  );
  return {
    ...actual,
    useConnections: vi.fn(),
    useAuthorize: vi.fn(),
    useUpdateConsents: vi.fn(),
    useDisconnect: vi.fn(),
  };
});

import {
  useAuthorize,
  useConnections,
  useDisconnect,
  useUpdateConsents,
} from "../wearables/queries";
import { WearablesSection } from "../wearables/wearables-section";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false }) as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = (over: object = {}) => ({ mutate: vi.fn(), isPending: false, ...over }) as any;

const CONNECTION = {
  id: "c1",
  member_id: "me",
  provider: "oura",
  status: "active",
  has_tokens: true,
  consent_types: ["wearable_sleep"],
  scopes: ["daily"],
  last_sync_at: "2026-07-27T04:20:00Z",
  last_error: null,
};

function renderSection(props: { connected?: string; callbackError?: string } = {}) {
  return render(
    <I18nProvider i18n={i18n}>
      <WearablesSection {...props} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useAuthorize).mockReturnValue(mutation());
  vi.mocked(useUpdateConsents).mockReturnValue(mutation());
  vi.mocked(useDisconnect).mockReturnValue(mutation());
  vi.mocked(useConnections).mockReturnValue(ok([]));
});

// --- connect flow -----------------------------------------------------------

test("without a connection it offers the consent picker and a connect button", () => {
  renderSection();
  expect(screen.getByText(i18n._("wearables.connect"))).toBeTruthy();
  expect(screen.getByLabelText(i18n._("wearables.type.sleep"))).toBeTruthy();
  expect(screen.getByLabelText(i18n._("wearables.type.heartrate"))).toBeTruthy();
});

test("connecting sends the ticked types and navigates to the provider", () => {
  const mutate = vi.fn();
  vi.mocked(useAuthorize).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByLabelText(i18n._("wearables.type.heartrate")));
  fireEvent.click(screen.getByText(i18n._("wearables.connect")));

  const [types] = mutate.mock.calls[0];
  // Sleep is preselected; the click adds heart rate.
  expect(new Set(types)).toEqual(new Set(["wearable_sleep", "wearable_heartrate"]));
});

test("connecting is impossible without at least one consent", () => {
  renderSection();
  fireEvent.click(screen.getByLabelText(i18n._("wearables.type.sleep"))); // untick the default
  const button = screen.getByText(i18n._("wearables.connect")).closest("button");
  expect(button?.disabled).toBe(true);
});

// --- an existing connection -------------------------------------------------

test("an existing connection shows its consented types ticked", () => {
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  renderSection();
  const sleep = screen.getByLabelText(i18n._("wearables.type.sleep")) as HTMLInputElement;
  const steps = screen.getByLabelText(i18n._("wearables.type.activity")) as HTMLInputElement;
  expect(sleep.checked).toBe(true);
  expect(steps.checked).toBe(false);
});

test("ticking a type patches the full new set, not a delta", () => {
  const mutate = vi.fn();
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  vi.mocked(useUpdateConsents).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByLabelText(i18n._("wearables.type.activity")));

  const [vars] = mutate.mock.calls[0];
  expect(vars.id).toBe("c1");
  expect(new Set(vars.consentTypes)).toEqual(new Set(["wearable_sleep", "wearable_activity"]));
});

test("unticking the last type is allowed — the backend then disconnects", () => {
  const mutate = vi.fn();
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  vi.mocked(useUpdateConsents).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByLabelText(i18n._("wearables.type.sleep")));

  expect(mutate.mock.calls[0][0].consentTypes).toEqual([]);
});

test("never renders a measured value", () => {
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  const { container } = renderSection();
  // The wire shape carries no score at all; this pins the intent so a future field cannot
  // quietly reach the DOM (Art. 9 — the UI says WHETHER, never WHAT).
  expect(container.textContent).not.toMatch(/\d{2,3}\s*(bpm|%)/);
});

// --- disconnect -------------------------------------------------------------

test("disconnecting asks first and names the consequence", () => {
  const mutate = vi.fn();
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  vi.mocked(useDisconnect).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByText(i18n._("wearables.disconnect")));
  expect(screen.getByText(i18n._("wearables.disconnectConfirm"))).toBeTruthy();
  expect(mutate).not.toHaveBeenCalled(); // the first click only confirms

  fireEvent.click(screen.getByText(i18n._("wearables.disconnectDo")));
  expect(mutate).toHaveBeenCalledWith("c1", expect.anything());
});

test("cancelling the confirm leaves the connection alone", () => {
  const mutate = vi.fn();
  vi.mocked(useConnections).mockReturnValue(ok([CONNECTION]));
  vi.mocked(useDisconnect).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByText(i18n._("wearables.disconnect")));
  fireEvent.click(screen.getByText(i18n._("wearables.cancel")));
  expect(mutate).not.toHaveBeenCalled();
  expect(screen.getByText(i18n._("wearables.disconnect"))).toBeTruthy();
});

// --- status + callback ------------------------------------------------------

test("an expired connection says so, and says it urgently", () => {
  vi.mocked(useConnections).mockReturnValue(
    ok([{ ...CONNECTION, status: "needs_reauth", last_error: "refresh_failed" }]),
  );
  renderSection();
  expect(screen.getByText(i18n._("wearables.status.needsReauth"))).toBeTruthy();
});

test("an operational hiccup is reported calmly, not as the member's problem", () => {
  vi.mocked(useConnections).mockReturnValue(ok([{ ...CONNECTION, last_error: "unreachable" }]));
  renderSection();
  expect(screen.getByText(i18n._("wearables.status.problem"))).toBeTruthy();
});

test("a cancelled authorisation is explained in plain words", () => {
  renderSection({ callbackError: "denied" });
  expect(screen.getByText(i18n._("wearables.cb.denied"))).toBeTruthy();
});

test("an unknown callback code still gets a human message", () => {
  renderSection({ callbackError: "something_new" });
  expect(screen.getByText(i18n._("wearables.cb.failed"))).toBeTruthy();
});

// --- error states -----------------------------------------------------------

test("a disabled provider is explained as an operator matter", () => {
  vi.mocked(useAuthorize).mockReturnValue(
    mutation({
      mutate: (_types: string[], opts: { onError: (e: unknown) => void }) =>
        opts.onError(new ProblemError("wearables_disabled")),
    }),
  );
  renderSection();
  fireEvent.click(screen.getByText(i18n._("wearables.connect")));
  expect(screen.getByText(i18n._("wearables.err.providerOff"))).toBeTruthy();
});

test("the loading and error trio is present", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useConnections).mockReturnValue({ isLoading: true, isError: false } as any);
  const { unmount } = renderSection();
  expect(screen.getByRole("status")).toBeTruthy();
  unmount();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useConnections).mockReturnValue({ isLoading: false, isError: true } as any);
  renderSection();
  expect(screen.getByRole("alert")).toBeTruthy();
});
