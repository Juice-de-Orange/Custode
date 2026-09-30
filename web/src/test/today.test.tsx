import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { dayOfWeekMondayZero } from "../lib/date";

// Stub the router Link (every tile renders a „view all" link) + useNavigate (signed-out
// redirect to /login, ADR-0078) so no router context is needed.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
  useNavigate: () => vi.fn(),
}));
vi.mock("../tasks/queries", () => ({ useTaskInstances: vi.fn() }));
vi.mock("../mealplan/queries", () => ({ useWeek: vi.fn() }));
vi.mock("../calendar/queries", () => ({ useTodayEvents: vi.fn() }));
vi.mock("../economy/queries", () => ({ useBalance: vi.fn() }));
vi.mock("../notes/queries", () => ({ usePinnedNotes: vi.fn() }));
vi.mock("../shopping/queries", () => ({
  useShoppingOpenCount: vi.fn(),
  useShoppingSync: vi.fn(),
}));
// No household in the stub session → the onboarding hero self-hides, so the tiles stay the subject.
vi.mock("../auth/session", () => ({ useSession: vi.fn(() => ({ data: undefined })) }));

import { useTodayEvents } from "../calendar/queries";
import { useBalance } from "../economy/queries";
import { useWeek } from "../mealplan/queries";
import { usePinnedNotes } from "../notes/queries";
import { TodayPage } from "../routes/today";
import { useShoppingOpenCount } from "../shopping/queries";
import { useTaskInstances } from "../tasks/queries";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false }) as any;

function renderToday() {
  render(
    <I18nProvider i18n={i18n}>
      <TodayPage />
    </I18nProvider>,
  );
}

function isoTodayNoon(): string {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

function isoInDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

beforeEach(() => {
  vi.mocked(useTaskInstances).mockReturnValue(ok([]));
  vi.mocked(useWeek).mockReturnValue(ok({ week_start: "", slots: [] }));
  vi.mocked(useTodayEvents).mockReturnValue(ok([]));
  vi.mocked(useBalance).mockReturnValue(ok({ balance: 0 }));
  vi.mocked(usePinnedNotes).mockReturnValue(ok([]));
  vi.mocked(useShoppingOpenCount).mockReturnValue(ok(0));
});

test("renders the localized title", () => {
  renderToday();
  expect(screen.getByRole("heading", { level: 1, name: "Heute" })).toBeInTheDocument();
});

test("renders every tile as a labelled region", () => {
  renderToday();
  for (const name of [
    "Aufgaben heute",
    "Heutige Mahlzeiten",
    "Termine heute",
    "Einkauf",
    "Punkte",
    "Angepinnte Notizen",
  ]) {
    expect(screen.getByRole("region", { name })).toBeInTheDocument();
  }
});

test("shows empty states across tiles when there is nothing for today", () => {
  renderToday();
  expect(screen.getByText("Nichts fällig — alles erledigt.")).toBeInTheDocument();
  expect(screen.getByText("Keine Termine heute.")).toBeInTheDocument();
  expect(screen.getByText("Keine offenen Artikel.")).toBeInTheDocument();
});

test("the tasks tile includes today's/overdue tasks and excludes future ones", () => {
  vi.mocked(useTaskInstances).mockReturnValue(
    ok([
      { id: "a", title: "Küche wischen", status: "open", due_at: isoTodayNoon(), points: 5 },
      { id: "b", title: "Überfällig gestern", status: "open", due_at: isoInDays(-1), points: 2 },
      { id: "c", title: "Erst übermorgen", status: "open", due_at: isoInDays(2), points: 3 },
      { id: "d", title: "Undatiert", status: "open", due_at: null, points: 1 },
    ]),
  );
  renderToday();
  expect(screen.getByText("Küche wischen")).toBeInTheDocument();
  expect(screen.getByText("Überfällig gestern")).toBeInTheDocument();
  expect(screen.queryByText("Erst übermorgen")).not.toBeInTheDocument();
  expect(screen.queryByText("Undatiert")).not.toBeInTheDocument();
});

test("the meals tile shows only today's slots", () => {
  const dow = dayOfWeekMondayZero(new Date());
  vi.mocked(useWeek).mockReturnValue(
    ok({
      week_start: "",
      slots: [
        { day_of_week: dow, slot: "dinner", recipe_title: "Pasta", free_text: null },
        { day_of_week: (dow + 1) % 7, slot: "dinner", recipe_title: "Morgen-Gericht", free_text: null },
      ],
    }),
  );
  renderToday();
  expect(screen.getByText("Pasta")).toBeInTheDocument();
  expect(screen.queryByText("Morgen-Gericht")).not.toBeInTheDocument();
});

test("the agenda tile lists today's events", () => {
  vi.mocked(useTodayEvents).mockReturnValue(
    ok([
      { id: "e1", title: "Zahnarzt", starts_at: isoTodayNoon(), all_day: false },
      { id: "e2", title: "Feiertag", starts_at: isoTodayNoon(), all_day: true },
    ]),
  );
  renderToday();
  expect(screen.getByText("Zahnarzt")).toBeInTheDocument();
  expect(screen.getByText("Feiertag")).toBeInTheDocument();
  expect(screen.getByText("ganztägig")).toBeInTheDocument();
});

test("counts and points render with correct ICU plurals", () => {
  vi.mocked(useShoppingOpenCount).mockReturnValue(ok(3));
  vi.mocked(useBalance).mockReturnValue(ok({ balance: 1 }));
  renderToday();
  expect(screen.getByText("3 offene Artikel")).toBeInTheDocument();
  expect(screen.getByText("1 Punkt")).toBeInTheDocument();
});

test("a loading tile shows the loading state", () => {
  vi.mocked(useBalance).mockReturnValue({ data: undefined, isLoading: true, isError: false } as never);
  renderToday();
  expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
});

test("an errored tile shows the error state", () => {
  vi.mocked(useTodayEvents).mockReturnValue({ data: undefined, isLoading: false, isError: true } as never);
  renderToday();
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
