import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

vi.mock("../household/queries", () => ({
  useMembers: vi.fn(),
  useChangeMemberRole: vi.fn(),
  useRemoveMember: vi.fn(),
  useLeaveHousehold: vi.fn(),
}));

import {
  useChangeMemberRole,
  useLeaveHousehold,
  useMembers,
  useRemoveMember,
} from "../household/queries";
import { MembersSection } from "../household/members-section";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = (over: object = {}) => ({ mutate: vi.fn(), isPending: false, ...over }) as any;
const query = (over: object = {}) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ({ data: [], isLoading: false, isError: false, isSuccess: true, ...over }) as any;

const ADMIN = {
  membership_id: "m-1",
  user_id: "u-1",
  role: "admin" as const,
  display_name: "Alex",
};
const MATE = {
  membership_id: "m-2",
  user_id: "u-2",
  role: "member" as const,
  display_name: "Robin",
};

function renderSection(opts: { isAdmin?: boolean; selfUserId?: string; onLeft?: () => void } = {}) {
  return render(
    <I18nProvider i18n={i18n}>
      <main>
        <MembersSection
          isAdmin={opts.isAdmin ?? true}
          selfUserId={opts.selfUserId ?? "u-1"}
          onLeft={opts.onLeft ?? (() => {})}
        />
      </main>
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useMembers).mockReturnValue(query({ data: [ADMIN, MATE] }));
  vi.mocked(useChangeMemberRole).mockReturnValue(mutation());
  vi.mocked(useRemoveMember).mockReturnValue(mutation());
  vi.mocked(useLeaveHousehold).mockReturnValue(mutation());
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => vi.restoreAllMocks());

// --- who sees which controls ------------------------------------------------

test("an admin can change roles and remove others, but never remove themselves", () => {
  renderSection({ isAdmin: true, selfUserId: "u-1" });

  // Two role selects (one per member), one remove button (for the other person only).
  expect(screen.getAllByRole("combobox")).toHaveLength(2);
  expect(screen.getAllByText(i18n._("members.remove"))).toHaveLength(1);
  // Leaving is the self-directed act and is offered instead.
  expect(screen.getByText(i18n._("members.leave"))).toBeTruthy();
});

test("a plain member sees the roster read-only — and can still leave", () => {
  renderSection({ isAdmin: false, selfUserId: "u-2" });

  expect(screen.queryAllByRole("combobox")).toHaveLength(0);
  expect(screen.queryByText(i18n._("members.remove"))).toBeNull();
  expect(screen.getByText(i18n._("members.leave"))).toBeTruthy();
});

// --- who must NOT be offered the exit ---------------------------------------

test("a child is never offered the exit — that account has no way back in", () => {
  const CHILD = {
    membership_id: "m-3",
    user_id: "u-3",
    role: "child" as const,
    display_name: "Kim",
  };
  vi.mocked(useMembers).mockReturnValue(query({ data: [ADMIN, CHILD] }));
  renderSection({ isAdmin: false, selfUserId: "u-3" });

  // No e-mail, no password, and `child_login` needs a live membership: leaving would be an
  // irreversible self-lockout behind a single confirm dialog. Removal by an adult is the way.
  expect(screen.queryByText(i18n._("members.leave"))).toBeNull();
  // The roster itself is still visible — this is not about hiding information.
  expect(screen.getByText("Kim")).toBeTruthy();
});

test("the exit is not offered before the roster has actually arrived", () => {
  // A query paused offline is neither loading nor loaded: `isLoading` is false while `data` is
  // undefined. Branching on that would show the button without knowing who else is in the house.
  vi.mocked(useMembers).mockReturnValue(
    query({ data: undefined, isLoading: false, isSuccess: false }),
  );
  renderSection();

  expect(screen.queryByText(i18n._("members.leave"))).toBeNull();
});

// --- the actions carry the right identifiers --------------------------------

test("changing a role sends that membership and the picked role", () => {
  const mutate = vi.fn();
  vi.mocked(useChangeMemberRole).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "admin" } });

  expect(mutate).toHaveBeenCalledWith(
    { membershipId: "m-2", role: "admin" },
    expect.anything(),
  );
});

test("removal asks first and sends the membership id, not the user id", () => {
  const mutate = vi.fn();
  vi.mocked(useRemoveMember).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByText(i18n._("members.remove")));

  expect(window.confirm).toHaveBeenCalled();
  expect(mutate).toHaveBeenCalledWith("m-2", expect.anything());
});

test("a declined confirmation removes nobody", () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const mutate = vi.fn();
  vi.mocked(useRemoveMember).mockReturnValue(mutation({ mutate }));
  renderSection();

  fireEvent.click(screen.getByText(i18n._("members.remove")));

  expect(mutate).not.toHaveBeenCalled();
});

// --- the three refusals are told apart --------------------------------------
// This is the point of the slice. The server answers 409 for all three, and collapsing them would
// tell somebody to hand a role to a person who does not exist.

test.each([
  ["last_admin", "members.err.lastAdmin"],
  ["only_children", "members.err.onlyChildren"],
  ["sole_member", "members.err.soleMember"],
])("a %s refusal shows its own sentence", (slug, messageId) => {
  vi.mocked(useLeaveHousehold).mockReturnValue(
    mutation({
      mutate: (_vars: unknown, opts: { onError: (e: unknown) => void }) =>
        opts.onError(new ProblemError(slug)),
    }),
  );
  renderSection();

  fireEvent.click(screen.getByText(i18n._("members.leave")));

  expect(screen.getByRole("alert").textContent).toContain(i18n._(messageId));
});

test("leaving successfully hands control back to the caller (which navigates away)", () => {
  const onLeft = vi.fn();
  vi.mocked(useLeaveHousehold).mockReturnValue(
    mutation({
      mutate: (_vars: unknown, opts: { onSuccess: () => void }) => opts.onSuccess(),
    }),
  );
  renderSection({ onLeft });

  fireEvent.click(screen.getByText(i18n._("members.leave")));

  expect(onLeft).toHaveBeenCalled();
});

// --- accessibility ----------------------------------------------------------

test("the roster has no axe violations", async () => {
  const { container } = renderSection();
  expect(await axe(container)).toHaveNoViolations();
});
