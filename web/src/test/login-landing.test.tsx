import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";

// Where a sign-in lands: a member of a household starts on "Today", the household's day — not on
// the account page. Without a household the account page is the deliberate first-run step
// (create or join one there).

const navigate = vi.fn();
let session: { user_id: string; household_id: string | null; role: string | null };

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
  useNavigate: () => navigate,
}));

vi.mock("../auth/session", async () => {
  const { ProblemError } = await import("../lib/problem");
  const signIn = {
    isPending: false,
    mutate: (_values: unknown, opts: { onSuccess: (s: typeof session) => void }) =>
      opts.onSuccess(session),
  };
  return { ProblemError, useLogin: () => signIn, usePasskeyLogin: () => signIn };
});

import { LoginPage } from "../routes/login";

beforeEach(() => {
  navigate.mockReset();
  // A normal instance: no demo.
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ enabled: false }))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function signIn() {
  render(
    <I18nProvider i18n={i18n}>
      <LoginPage />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "a@example.org" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "a-long-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
}

test("a member lands on Today", async () => {
  session = { user_id: "u1", household_id: "h1", role: "admin" };
  signIn();
  await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: "/today" }));
});

test("an account without a household lands on the account page to create or join one", async () => {
  session = { user_id: "u1", household_id: null, role: null };
  signIn();
  await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: "/" }));
});
