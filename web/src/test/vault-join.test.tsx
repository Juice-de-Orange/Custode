import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import type { EnvelopeResponse, EnvelopeUpsert } from "../api/types.gen";
import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

// Regression for BUGLOG 2026-10-03 (data-loss class). A household's second member opened /vault
// and was offered "Tresor einrichten": `setup()` generated a NEW household key and replaced the
// household-wide recovery envelope. The first member's recovery code stopped working and her
// entries were unreadable to the second.
//
// The crypto here is the real one (libsodium) — the point of the test is which key ends up
// inside which envelope, and a mocked wrap/unwrap could not show that. Only the HTTP layer is
// replaced, by an in-memory server that behaves like the real one where it matters: the recovery
// envelope is write-once (409 `vault_already_set_up`).

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

const state = vi.hoisted(() => ({
  session: { user_id: "member-b", role: "member" as string },
  envelopes: [] as EnvelopeResponse[],
  puts: [] as EnvelopeUpsert[],
  keysEnabled: [] as boolean[],
  rerender: () => {},
  // One stable array: the page's decrypt effect depends on `items.data` by identity.
  noItems: [] as never[],
}));

vi.mock("../auth/session", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSession: () => ({ data: state.session, isLoading: false }),
}));

vi.mock("../vault/queries", () => ({
  useVaultKeys: (enabled = true) => {
    state.keysEnabled.push(enabled);
    const mine = state.envelopes.filter(
      (e) => e.kind === "recovery" || e.member_id === state.session.user_id,
    );
    return { data: enabled ? mine : undefined, isLoading: false, isError: false, refetch: vi.fn() };
  },
  usePutKey: () => ({
    isPending: false,
    mutateAsync: async (body: EnvelopeUpsert) => {
      state.puts.push(body);
      const memberId = body.kind === "passphrase" ? state.session.user_id : null;
      if (body.kind === "recovery" && state.envelopes.some((e) => e.kind === "recovery")) {
        throw new ProblemError("vault_already_set_up");
      }
      state.envelopes = [
        ...state.envelopes.filter((e) => !(e.kind === body.kind && e.member_id === memberId)),
        {
          id: `env-${state.envelopes.length}`,
          member_id: memberId,
          kind: body.kind,
          key_version: 1,
          wrapped_key: body.wrapped_key,
          wrap_meta: body.wrap_meta ?? {},
          created_at: "2026-10-03T00:00:00Z",
        },
      ];
      state.rerender();
    },
  }),
  useVaultItems: () => ({ data: state.noItems, isLoading: false, isError: false }),
  useVaultItem: () => ({ data: undefined, isLoading: false }),
  useCreateItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteItem: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { VaultPage } from "../routes/vault";
import {
  generateHouseholdKey,
  unwrapHouseholdKey,
  wrapHouseholdKey,
  type WrapMeta,
} from "../vault/crypto";

const RECOVERY_CODE = "ABCDE-FGHIJ-KLMNO-PQRST";
const tree = () => (
  <I18nProvider i18n={i18n}>
    <VaultPage />
  </I18nProvider>
);

function renderVault() {
  const view = render(tree());
  state.rerender = () => view.rerender(tree());
}

const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

/** Member A set the vault up earlier: her passphrase envelope plus the household recovery one. */
async function vaultOfMemberA(): Promise<Uint8Array> {
  const key = await generateHouseholdKey();
  const pass = await wrapHouseholdKey(key, "passphrase-von-a");
  const rec = await wrapHouseholdKey(key, RECOVERY_CODE);
  const base = { key_version: 1, created_at: "2026-10-01T00:00:00Z" };
  state.envelopes = [
    { ...base, id: "a-pass", member_id: "member-a", kind: "passphrase", ...pass },
    { ...base, id: "hh-rec", member_id: null, kind: "recovery", ...rec },
  ];
  return key;
}

beforeEach(() => {
  state.session = { user_id: "member-b", role: "member" };
  state.envelopes = [];
  state.puts = [];
  state.keysEnabled = [];
});

test("a second member joins the existing vault: same household key, recovery envelope untouched", async () => {
  const householdKey = await vaultOfMemberA();
  const recoveryBefore = state.envelopes.find((e) => e.kind === "recovery");
  renderVault();

  // No setup form for a household that already has a vault.
  expect(screen.queryByRole("button", { name: "Tresor einrichten" })).toBeNull();
  expect(screen.getByText(/bereits eingerichtet/)).toBeInTheDocument();

  // A wrong code is refused and stores nothing.
  fireEvent.change(screen.getByLabelText("Wiederherstellungs-Code"), {
    target: { value: "FALSC-HERCO-DE000-00000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tresor beitreten" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Falscher Wiederherstellungs-Code.");
  expect(state.puts).toEqual([]);

  // The household's code opens it; the unlocked vault asks for an own passphrase.
  fireEvent.change(screen.getByLabelText("Wiederherstellungs-Code"), {
    target: { value: RECOVERY_CODE },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tresor beitreten" }));
  expect(await screen.findByText("Neue Passphrase setzen")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Vault-Passphrase"), {
    target: { value: "passphrase-von-b" },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "Speichern" })[0]);
  await waitFor(() => expect(state.puts).toHaveLength(1));

  // Exactly one write: B's own passphrase envelope. Never a recovery envelope.
  expect(state.puts.map((p) => p.kind)).toEqual(["passphrase"]);
  expect(state.envelopes.find((e) => e.kind === "recovery")).toEqual(recoveryBefore);

  // B's envelope wraps A's household key — the same bytes, not a new key.
  const mine = state.envelopes.find((e) => e.member_id === "member-b");
  const unwrapped = await unwrapHouseholdKey(
    mine!.wrapped_key,
    mine!.wrap_meta as unknown as WrapMeta,
    "passphrase-von-b",
  );
  expect(hex(unwrapped)).toBe(hex(householdKey));

  // And A's recovery code still opens the vault afterwards.
  const viaRecovery = await unwrapHouseholdKey(
    recoveryBefore!.wrapped_key,
    recoveryBefore!.wrap_meta as unknown as WrapMeta,
    RECOVERY_CODE,
  );
  expect(hex(viaRecovery)).toBe(hex(householdKey));
}, 60_000);

test("first setup claims the recovery envelope before storing the passphrase envelope", async () => {
  state.session = { user_id: "member-a", role: "admin" };
  renderVault();
  expect(screen.getByText(/Lege eine Vault-Passphrase fest/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Vault-Passphrase"), {
    target: { value: "passphrase-von-a" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tresor einrichten" }));
  await waitFor(() => expect(state.puts).toHaveLength(2), { timeout: 30_000 });
  expect(state.puts.map((p) => p.kind)).toEqual(["recovery", "passphrase"]);
  // Both envelopes carry one and the same key; the code shown opens the recovery one.
  const code = (await screen.findAllByText(/^[A-Z0-9_-]+(-[A-Z0-9_-]+)+$/))[0].textContent ?? "";
  const [rec, pass] = state.puts;
  const viaCode = await unwrapHouseholdKey(rec.wrapped_key, rec.wrap_meta as unknown as WrapMeta, code);
  const viaPass = await unwrapHouseholdKey(
    pass.wrapped_key,
    pass.wrap_meta as unknown as WrapMeta,
    "passphrase-von-a",
  );
  expect(hex(viaCode)).toBe(hex(viaPass));
}, 60_000);

test("a setup that loses the race stores no passphrase envelope and says why", async () => {
  state.session = { user_id: "member-b", role: "member" };
  renderVault(); // empty when the page loaded …
  fireEvent.change(screen.getByLabelText("Vault-Passphrase"), {
    target: { value: "passphrase-von-b" },
  });
  await vaultOfMemberA(); // … but A finished her setup before B pressed the button
  fireEvent.click(screen.getByRole("button", { name: "Tresor einrichten" }));
  expect(await screen.findByRole("alert", {}, { timeout: 30_000 })).toHaveTextContent(
    /inzwischen von einem anderen Mitglied eingerichtet/,
  );
  expect(state.puts.map((p) => p.kind)).toEqual(["recovery"]); // refused, and nothing after it
  expect(state.envelopes.some((e) => e.member_id === "member-b")).toBe(false);
}, 60_000);

test("a child account sees 'not available' and the keys are never requested", () => {
  state.session = { user_id: "kid", role: "child" };
  renderVault();
  expect(
    screen.getByText("Der Tresor steht Kinder- und Gastkonten nicht zur Verfügung."),
  ).toBeInTheDocument();
  expect(screen.queryByText("Etwas ist schiefgelaufen.")).toBeNull();
  expect(state.keysEnabled.every((enabled) => enabled === false)).toBe(true);
});
