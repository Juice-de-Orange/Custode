import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

vi.mock("../calendar/queries", () => ({
  useSubscriptions: vi.fn(),
  useSubscription: vi.fn(),
  useCheckSubscription: vi.fn(),
  useCreateSubscription: vi.fn(),
  useUpdateSubscription: vi.fn(),
  useToggleSubscription: vi.fn(),
  useDeleteSubscription: vi.fn(),
}));

import {
  checkMessage,
  SubscriptionsSection,
  syncStatus,
} from "../calendar/subscriptions-section";
import {
  useCheckSubscription,
  useCreateSubscription,
  useDeleteSubscription,
  useSubscription,
  useSubscriptions,
  useToggleSubscription,
  useUpdateSubscription,
} from "../calendar/queries";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false, refetch: vi.fn() }) as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = () => ({ mutate: vi.fn(), isPending: false }) as any;

const SUB = {
  id: "s1",
  member_id: "me",
  label: "Nextcloud",
  caldav_url: "https://cloud.example.de/remote.php/dav/calendars/max/privat/",
  enabled: true,
  has_credentials: true,
  last_sync_at: "2026-07-23T06:00:00Z",
  last_sync_error: null,
};

function renderSection() {
  render(
    <I18nProvider i18n={i18n}>
      <SubscriptionsSection />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  vi.mocked(useSubscription).mockReturnValue(ok(undefined));
  vi.mocked(useCheckSubscription).mockReturnValue(mutation());
  vi.mocked(useCreateSubscription).mockReturnValue(mutation());
  vi.mocked(useUpdateSubscription).mockReturnValue(mutation());
  vi.mocked(useToggleSubscription).mockReturnValue(mutation());
  vi.mocked(useDeleteSubscription).mockReturnValue(mutation());
});

test("empty state offers the add CTA", () => {
  vi.mocked(useSubscriptions).mockReturnValue(ok([]));
  renderSection();
  expect(screen.getByText("Noch keine externen Kalender abonniert.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Abo hinzufügen" })).toBeInTheDocument();
});

test("card shows label, url, credentials hint and last sync", () => {
  renderSection();
  expect(screen.getByText("Nextcloud")).toBeInTheDocument();
  expect(screen.getByText(/remote\.php\/dav/)).toBeInTheDocument();
  expect(screen.getByText(/Zugangsdaten hinterlegt/)).toBeInTheDocument();
  expect(screen.getByText(/Zuletzt synchronisiert:/)).toBeInTheDocument();
});

test("sync error category renders its German text", () => {
  vi.mocked(useSubscriptions).mockReturnValue(ok([{ ...SUB, last_sync_error: "auth_failed" }]));
  renderSection();
  expect(
    screen.getByText(/Anmeldung fehlgeschlagen — prüfe Benutzername und Passwort\./),
  ).toBeInTheDocument();
});

test("paused beats a stale sync error", () => {
  vi.mocked(useSubscriptions).mockReturnValue(
    ok([{ ...SUB, enabled: false, last_sync_error: "unreachable" }]),
  );
  renderSection();
  expect(screen.getByText(/^Pausiert/)).toBeInTheDocument();
  expect(screen.queryByText(/Server nicht erreichbar/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Fortsetzen" })).toBeInTheDocument();
});

test("create sends the pair only when both fields are filled", () => {
  const create = mutation();
  vi.mocked(useCreateSubscription).mockReturnValue(create);
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Abo hinzufügen" }));
  fireEvent.change(screen.getByLabelText("Bezeichnung"), { target: { value: "Neu" } });
  fireEvent.change(screen.getByLabelText("CalDAV-URL"), {
    target: { value: "https://cal.example.org/dav/" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Abonnieren" }));
  expect(create.mutate).toHaveBeenCalledWith(
    { label: "Neu", caldav_url: "https://cal.example.org/dav/" },
    expect.anything(),
  );

  fireEvent.change(screen.getByLabelText("Benutzername (optional)"), {
    target: { value: "max" },
  });
  fireEvent.change(screen.getByLabelText("Passwort (optional)"), {
    target: { value: "geheim" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Abonnieren" }));
  expect(create.mutate).toHaveBeenLastCalledWith(
    {
      label: "Neu",
      caldav_url: "https://cal.example.org/dav/",
      username: "max",
      password: "geheim",
    },
    expect.anything(),
  );
});

test("a duplicate answers with the exists message", () => {
  const create = mutation();
  create.mutate.mockImplementation(
    (_vars: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ProblemError("subscription_exists")),
  );
  vi.mocked(useCreateSubscription).mockReturnValue(create);
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Abo hinzufügen" }));
  fireEvent.change(screen.getByLabelText("Bezeichnung"), { target: { value: "Neu" } });
  fireEvent.change(screen.getByLabelText("CalDAV-URL"), {
    target: { value: "https://cal.example.org/dav/" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Abonnieren" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Für diese URL hast du bereits ein Abo.");
});

test("pause toggle flips enabled", () => {
  const toggle = mutation();
  vi.mocked(useToggleSubscription).mockReturnValue(toggle);
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Pausieren" }));
  expect(toggle.mutate).toHaveBeenCalledWith({ id: "s1", enabled: false }, expect.anything());
});

test("delete asks for confirmation first", () => {
  const remove = mutation();
  vi.mocked(useDeleteSubscription).mockReturnValue(remove);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Löschen" }));
  expect(remove.mutate).not.toHaveBeenCalled();
  confirmSpy.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Löschen" }));
  expect(remove.mutate).toHaveBeenCalledWith("s1", expect.anything());
  confirmSpy.mockRestore();
});

test("edit prefills label/url but never the password; clear_credentials round-trips", () => {
  const update = mutation();
  vi.mocked(useUpdateSubscription).mockReturnValue(update);
  vi.mocked(useSubscription).mockReturnValue(ok({ ...SUB, etag: '"3"' }));
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Bearbeiten" }));
  expect(screen.getByLabelText("Bezeichnung")).toHaveValue("Nextcloud");
  expect(screen.getByLabelText("Passwort (optional)")).toHaveValue(""); // write-only
  fireEvent.click(screen.getByLabelText("Zugangsdaten entfernen"));
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
  expect(update.mutate).toHaveBeenCalledWith(
    {
      id: "s1",
      etag: '"3"',
      update: { label: "Nextcloud", caldav_url: SUB.caldav_url, clear_credentials: true },
    },
    expect.anything(),
  );
});

test("a stale edit (412) refetches the detail for a retry", () => {
  const update = mutation();
  update.mutate.mockImplementation(
    (_vars: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ProblemError("precondition_failed")),
  );
  vi.mocked(useUpdateSubscription).mockReturnValue(update);
  const detail = ok({ ...SUB, etag: '"3"' });
  vi.mocked(useSubscription).mockReturnValue(detail);
  renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Bearbeiten" }));
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/zwischenzeitlich geändert/);
  expect(detail.refetch).toHaveBeenCalled();
});

test("syncStatus precedence: paused > error > success > never", () => {
  expect(syncStatus({ ...SUB, enabled: false }).ref.id).toBe("calendar.subs.paused");
  expect(syncStatus({ ...SUB, last_sync_error: "unreachable" }).tone).toBe("error");
  expect(syncStatus(SUB).ref.id).toBe("calendar.subs.lastSync");
  expect(syncStatus({ ...SUB, last_sync_at: null }).ref.id).toBe("calendar.subs.neverSynced");
});

// --- connection probe (P9) ----------------------------------------------------

test("checking a subscription reports the result inline", () => {
  const mutate = vi.fn((_id: string, opts: { onSuccess: (r: unknown) => void }) =>
    opts.onSuccess({ ok: true, category: null, objects: 7 }),
  );
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useCheckSubscription).mockReturnValue({ mutate, isPending: false } as any);
  renderSection();

  fireEvent.click(screen.getByText(i18n._("calendar.subs.check")));

  expect(mutate).toHaveBeenCalledWith("s1", expect.anything());
  // The probe result lives in its own status region — naming the count makes
  // "reachable but empty" distinguishable from "reachable with data".
  expect(screen.getByRole("status").textContent).toContain("7");
});

test("a failed probe speaks the same language as the sync status", () => {
  const mutate = vi.fn((_id: string, opts: { onSuccess: (r: unknown) => void }) =>
    opts.onSuccess({ ok: false, category: "auth_failed", objects: null }),
  );
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useCheckSubscription).mockReturnValue({ mutate, isPending: false } as any);
  renderSection();

  fireEvent.click(screen.getByText(i18n._("calendar.subs.check")));
  expect(screen.getByText(i18n._("calendar.subs.sync.auth_failed"))).toBeTruthy();
});

test("checkMessage maps both outcomes onto catalogue ids", () => {
  expect(checkMessage({ ok: true, category: null, objects: 0 })).toEqual({
    id: "calendar.subs.checkOk",
    values: { count: "0" },
  });
  expect(checkMessage({ ok: false, category: "unreachable", objects: null }).id).toBe(
    "calendar.subs.sync.unreachable",
  );
  // An unknown category still gets a human message, never a raw slug.
  expect(checkMessage({ ok: false, category: "brand_new", objects: null }).id).toBe(
    "calendar.subs.sync.failed",
  );
});
