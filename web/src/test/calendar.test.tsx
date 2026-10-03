import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));
vi.mock("../auth/session", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSession: vi.fn(() => ({
    data: { user_id: "me", flags: [], role: "member" },
    isLoading: false,
  })),
}));
vi.mock("../calendar/queries", () => ({
  useEvents: vi.fn(),
  useCreateEvent: vi.fn(),
  useDeleteEvent: vi.fn(),
  useCancelOccurrence: vi.fn(),
  useMoveOccurrence: vi.fn(),
  useCreateFeed: vi.fn(),
  useDeleteFeed: vi.fn(),
  useImportIcs: vi.fn(),
  useSubscriptions: vi.fn(),
}));
// The subscriptions section has its own test suite — keep the route test focused.
vi.mock("../calendar/subscriptions-section", () => ({
  SubscriptionsSection: () => null,
}));
vi.mock("../scheduling/panel", () => ({ SchedulingPanel: () => null }));
vi.mock("../weather/card", () => ({ WeatherCard: () => null }));

import {
  useCancelOccurrence,
  useCreateEvent,
  useCreateFeed,
  useDeleteEvent,
  useDeleteFeed,
  useEvents,
  useImportIcs,
  useMoveOccurrence,
  useSubscriptions,
} from "../calendar/queries";
import { CalendarPage } from "../routes/calendar";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false }) as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mutation = () => ({ mutate: vi.fn(), isPending: false }) as any;

const BASE_EVENT = {
  id: "e1",
  series_id: "e1",
  owner_id: "me",
  title: "Zahnarzt",
  description: null,
  location: null,
  starts_at: "2026-08-01T09:00:00Z",
  ends_at: "2026-08-01T10:00:00Z",
  original_start: null,
  all_day: false,
  layer: "personal",
  busy: true,
  kind: "normal",
  rrule: null,
  recurring: false,
  exdates: [],
  tzid: "UTC",
  external: false,
};

const SUB = {
  id: "s1",
  member_id: "me",
  label: "Nextcloud",
  caldav_url: "https://cloud.example.de/dav/",
  enabled: true,
  has_credentials: true,
  last_sync_at: null,
  last_sync_error: null,
};

function renderCalendar() {
  render(
    <I18nProvider i18n={i18n}>
      <CalendarPage />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useEvents).mockReturnValue(ok([]));
  vi.mocked(useCreateEvent).mockReturnValue(mutation());
  vi.mocked(useDeleteEvent).mockReturnValue(mutation());
  vi.mocked(useCancelOccurrence).mockReturnValue(mutation());
  vi.mocked(useMoveOccurrence).mockReturnValue(mutation());
  vi.mocked(useCreateFeed).mockReturnValue(mutation());
  vi.mocked(useDeleteFeed).mockReturnValue(mutation());
  vi.mocked(useImportIcs).mockReturnValue(mutation());
  vi.mocked(useSubscriptions).mockReturnValue(ok([]));
});

test("external events carry the badge and hide occurrence actions", () => {
  vi.mocked(useEvents).mockReturnValue(
    ok([
      {
        ...BASE_EVENT,
        id: "ext1",
        series_id: "ext1",
        title: "Extern-Serie",
        recurring: true,
        rrule: "FREQ=WEEKLY",
        original_start: "2026-08-01T09:00:00Z",
        external: true,
      },
      {
        ...BASE_EVENT,
        id: "loc1",
        series_id: "loc1",
        title: "Lokal-Serie",
        recurring: true,
        rrule: "FREQ=WEEKLY",
        original_start: "2026-08-02T09:00:00Z",
      },
    ]),
  );
  renderCalendar();
  expect(screen.getByText("Extern")).toBeInTheDocument();
  // The local series offers move/cancel, the external one does not — exactly one of each.
  expect(screen.getAllByRole("button", { name: "Verschieben" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "Diesen Termin absagen" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "Löschen" })).toHaveLength(2);
});

test("the target select appears only when subscriptions exist", () => {
  renderCalendar();
  expect(screen.queryByLabelText("Ziel-Kalender")).not.toBeInTheDocument();
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  renderCalendar();
  expect(screen.getByLabelText("Ziel-Kalender")).toBeInTheDocument();
});

test("creating into a subscription forces personal/normal/UTC", () => {
  const create = mutation();
  vi.mocked(useCreateEvent).mockReturnValue(create);
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  renderCalendar();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Nach draußen" } });
  fireEvent.change(screen.getByLabelText("Beginn"), {
    target: { value: "2026-08-01T09:00" },
  });
  fireEvent.change(screen.getByLabelText("Ende"), { target: { value: "2026-08-01T10:00" } });
  fireEvent.change(screen.getByLabelText("Ziel-Kalender"), { target: { value: "s1" } });
  expect(screen.getByText(/Wird im externen Kalender angelegt/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Termin anlegen" }));
  expect(create.mutate).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "Nach draußen",
      layer: "personal",
      kind: "normal",
      tzid: "UTC",
      subscription_id: "s1",
    }),
    expect.anything(),
  );
});

test("a failed create keeps the input and shows the mapped error", () => {
  const create = mutation();
  create.mutate.mockImplementation(
    (_vars: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ProblemError("caldav_disabled")),
  );
  vi.mocked(useCreateEvent).mockReturnValue(create);
  vi.mocked(useSubscriptions).mockReturnValue(ok([SUB]));
  renderCalendar();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Bleibt stehen" } });
  fireEvent.change(screen.getByLabelText("Beginn"), {
    target: { value: "2026-08-01T09:00" },
  });
  fireEvent.change(screen.getByLabelText("Ende"), { target: { value: "2026-08-01T10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Termin anlegen" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "CalDAV-Sync ist auf diesem Server deaktiviert.",
  );
  expect(screen.getByLabelText("Titel")).toHaveValue("Bleibt stehen"); // no premature reset
});

test("deleting an external event asks for confirmation, a local one does not", () => {
  const remove = mutation();
  vi.mocked(useDeleteEvent).mockReturnValue(remove);
  vi.mocked(useEvents).mockReturnValue(
    ok([
      { ...BASE_EVENT, id: "ext1", series_id: "ext1", title: "Externer", external: true },
      { ...BASE_EVENT, id: "loc1", series_id: "loc1", title: "Lokaler" },
    ]),
  );
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderCalendar();
  const [externalDelete, localDelete] = screen.getAllByRole("button", { name: "Löschen" });

  fireEvent.click(externalDelete);
  expect(confirmSpy).toHaveBeenCalledTimes(1);
  expect(remove.mutate).not.toHaveBeenCalled(); // declined

  confirmSpy.mockReturnValue(true);
  fireEvent.click(externalDelete);
  expect(remove.mutate).toHaveBeenCalledWith("ext1", expect.anything());

  confirmSpy.mockClear();
  fireEvent.click(localDelete);
  expect(confirmSpy).not.toHaveBeenCalled(); // local deletes stay one-click
  expect(remove.mutate).toHaveBeenLastCalledWith("loc1", expect.anything());
  confirmSpy.mockRestore();
});

test("an end before the start is reported at the end field and nothing is sent", () => {
  const create = mutation();
  vi.mocked(useCreateEvent).mockReturnValue(create);
  renderCalendar();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Zahnarzt" } });
  fireEvent.change(screen.getByLabelText("Beginn"), { target: { value: "2026-10-05T10:00" } });
  fireEvent.change(screen.getByLabelText("Ende"), { target: { value: "2026-10-05T09:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Termin anlegen" }));

  const end = screen.getByLabelText("Ende");
  expect(end).toHaveAttribute("aria-invalid", "true");
  expect(document.getElementById(end.getAttribute("aria-describedby") ?? "")).toHaveTextContent(
    "Das Ende darf nicht vor dem Beginn liegen.",
  );
  expect(create.mutate).not.toHaveBeenCalled();

  // Counter-check: correcting the end clears the error and the event goes out.
  fireEvent.change(screen.getByLabelText("Ende"), { target: { value: "2026-10-05T11:00" } });
  expect(screen.getByLabelText("Ende")).not.toHaveAttribute("aria-invalid");
  fireEvent.click(screen.getByRole("button", { name: "Termin anlegen" }));
  expect(create.mutate).toHaveBeenCalledOnce();
});
