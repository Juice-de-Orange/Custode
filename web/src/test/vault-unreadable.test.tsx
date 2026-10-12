import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import type { EnvelopeResponse, VaultItemSummary } from "../api/types.gen";
import { i18n } from "../i18n";

// An entry this member cannot decrypt (it was encrypted under another household key — e.g. by a
// stale client that stored a lone key, BUGLOG 2026-10-03) used to show as "??" with a one-click
// delete button. For somebody else in the household that entry may well be readable, so a
// single click could destroy their secret without any hint of what it was. The list now says
// what the entry is and asks before deleting it; readable entries keep the direct button.

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

const state = vi.hoisted(() => ({
  envelopes: [] as EnvelopeResponse[],
  items: [] as VaultItemSummary[],
  deleted: [] as string[],
}));

vi.mock("../auth/session", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSession: () => ({ data: { user_id: "member-b", role: "member" }, isLoading: false }),
}));

vi.mock("../vault/queries", () => ({
  useVaultKeys: () => ({ data: state.envelopes, isLoading: false, isError: false, refetch: vi.fn() }),
  usePutKey: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useVaultItems: () => ({ data: state.items, isLoading: false, isError: false }),
  useVaultItem: () => ({ data: undefined, isLoading: false }),
  useCreateItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteItem: () => ({ mutate: (id: string) => state.deleted.push(id), isPending: false }),
}));

import { VaultPage } from "../routes/vault";
import { encryptItem, generateHouseholdKey, wrapHouseholdKey } from "../vault/crypto";

function item(id: string, enc: { ciphertext: string; item_meta: unknown }): VaultItemSummary {
  return {
    id,
    key_version: 1,
    item_meta: enc.item_meta as VaultItemSummary["item_meta"],
    author_id: "member-a",
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  } as VaultItemSummary;
}

beforeEach(async () => {
  const mine = await generateHouseholdKey();
  const other = await generateHouseholdKey(); // a key this member never had
  const pass = await wrapHouseholdKey(mine, "passphrase-von-b");
  state.envelopes = [
    {
      id: "b-pass",
      member_id: "member-b",
      kind: "passphrase",
      key_version: 1,
      created_at: "2026-10-01T00:00:00Z",
      ...pass,
    },
  ];
  state.items = [
    item("readable", await encryptItem("WLAN", "secret-1", mine)),
    item("foreign", await encryptItem("Bank", "secret-2", other)),
  ];
  state.deleted = [];
});

async function unlocked() {
  render(
    <I18nProvider i18n={i18n}>
      <VaultPage />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByLabelText("Vault-Passphrase"), {
    target: { value: "passphrase-von-b" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Entsperren" }));
  await screen.findByText("WLAN", {}, { timeout: 30_000 });
}

test("an undecryptable entry is labelled and only deleted after an explicit confirmation", async () => {
  await unlocked();
  expect(screen.queryByText("??")).toBeNull();
  const foreign = (await screen.findByText("Unlesbarer Eintrag")).closest("li")!;
  expect(foreign).toHaveTextContent(/anderen Schlüssel/);

  // First click only asks.
  fireEvent.click(foreign.querySelector("button[data-action='delete']")!);
  expect(state.deleted).toEqual([]);
  expect(foreign).toHaveTextContent(/für andere Mitglieder/);

  // Cancel keeps it …
  fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
  expect(state.deleted).toEqual([]);

  // … the confirmation deletes it.
  fireEvent.click(foreign.querySelector("button[data-action='delete']")!);
  fireEvent.click(screen.getByRole("button", { name: "Trotzdem löschen" }));
  expect(state.deleted).toEqual(["foreign"]);
}, 60_000);

test("a readable entry keeps its direct delete button", async () => {
  await unlocked();
  const readable = screen.getByText("WLAN").closest("li")!;
  fireEvent.click(readable.querySelector("button[data-action='delete']")!);
  expect(state.deleted).toEqual(["readable"]);
}, 60_000);
