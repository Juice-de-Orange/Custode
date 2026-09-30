import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";

// Trio regression (BUGLOG 2026-07-19): the Dexie orderBy bug silently error-stated the primary
// queries and the route rendered as "empty" instead of showing an error. The fix in
// shopping/queries.ts removed the throw; these tests pin the route-level guarantee that a failing
// primary query now surfaces the ErrorState (role="alert"), never the empty/first-list flow.
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));
vi.mock("../auth/session", () => ({
  useSession: vi.fn(() => ({ data: { user_id: "me" }, isLoading: false })),
}));
vi.mock("../lib/useOnline", () => ({ useOnline: () => true }));
vi.mock("../shopping/sync", () => ({ sync: vi.fn() }));
vi.mock("../shopping/queries", () => ({
  useShoppingLists: vi.fn(),
  useShoppingItems: vi.fn(),
  useShoppingCatalog: vi.fn(),
  useShoppingBasics: vi.fn(),
  useShoppingActions: vi.fn(),
  useShoppingSync: vi.fn(),
}));

import { ShoppingPage } from "../routes/shopping";
import {
  useShoppingActions,
  useShoppingBasics,
  useShoppingCatalog,
  useShoppingItems,
  useShoppingLists,
} from "../shopping/queries";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false }) as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const errored = () => ({ data: undefined, isLoading: false, isError: true }) as any;

function renderShopping() {
  render(
    <I18nProvider i18n={i18n}>
      <ShoppingPage />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useShoppingLists).mockReturnValue(ok([]));
  vi.mocked(useShoppingItems).mockReturnValue(ok([]));
  vi.mocked(useShoppingCatalog).mockReturnValue(ok([]));
  vi.mocked(useShoppingBasics).mockReturnValue(ok([]));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useShoppingActions).mockReturnValue({ mutate: vi.fn() } as any);
});

test("a failing lists query shows the error state, not the first-list flow", () => {
  vi.mocked(useShoppingLists).mockReturnValue(errored());
  renderShopping();
  expect(screen.getByRole("alert")).toBeInTheDocument();
  // The "create your first list" form must not appear — an error is not an empty household.
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

test("a failing items query shows the error state instead of the empty list", () => {
  vi.mocked(useShoppingLists).mockReturnValue(ok([{ id: "l1", name: "Wocheneinkauf" }]));
  vi.mocked(useShoppingItems).mockReturnValue(errored());
  renderShopping();
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

test("healthy empty queries keep rendering the quiet empty state", () => {
  vi.mocked(useShoppingLists).mockReturnValue(ok([{ id: "l1", name: "Wocheneinkauf" }]));
  renderShopping();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
