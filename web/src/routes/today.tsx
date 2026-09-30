import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { Pin } from "lucide-react";
import { useEffect } from "react";

import type { MealSlotResponse } from "../api/types.gen";
import { useSession } from "../auth/session";
import { DashboardTile } from "../components/dashboard-tile";
import { InstallHintCard } from "../components/install-app";
import { OnboardingPresets } from "../components/preset-picker";
import { LandscapeScene } from "../components/scenes/landscape-scene";
import { LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { dayOfWeekMondayZero, mondayOf, todayRange } from "../lib/date";
import { useBalance } from "../economy/queries";
import { useTodayEvents } from "../calendar/queries";
import { useWeek } from "../mealplan/queries";
import { usePinnedNotes } from "../notes/queries";
import { useShoppingOpenCount, useShoppingSync } from "../shopping/queries";
import { useTaskInstances } from "../tasks/queries";

// Cap each list tile so the page stays calm; a „+N weitere" line links into the module for the rest.
const MAX_ROWS = 5;
const SLOT_ORDER: Record<MealSlotResponse["slot"], number> = {
  breakfast: 0,
  lunch: 1,
  dinner: 2,
  snack: 3,
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(i18n.locale, { hour: "2-digit", minute: "2-digit" });
}

// „Heute" — the cross-cutting start page (S-21). Calm tiles that summarise the day across modules:
// tasks due, today's meals, today's agenda, open shopping, points, pinned notes. Every tile reuses
// existing query keys, so the realtime SSE map (RootLayout) keeps them live.
export function TodayPage() {
  const now = new Date();
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();

  // start_url of the installed PWA (ADR-0078): signed-out lands on /login instead of a wall of
  // error tiles. Offline keeps the page (fetchMe then errors, data stays undefined — not null).
  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);
  const dateLabel = now.toLocaleDateString(i18n.locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const showOnboarding = !!session?.household_id && session.role === "admin";
  const weekStart = mondayOf(now);
  const dow = dayOfWeekMondayZero(now);
  const range = todayRange(now);
  const endOfDay = new Date(range.to).getTime();

  const tasks = useTaskInstances();
  const week = useWeek(weekStart);
  const events = useTodayEvents(range);
  const balance = useBalance();
  const pinned = usePinnedNotes();

  // Shopping lives in the offline cache; pull the latest in, then count what's still open.
  useShoppingSync();
  const openCount = useShoppingOpenCount();

  // Open instances due today or overdue (undated chores stay on /tasks), soonest first.
  const dueTasks = (tasks.data ?? [])
    .filter((i) => i.status === "open" && i.due_at !== null && new Date(i.due_at).getTime() <= endOfDay)
    .sort((a, b) => new Date(a.due_at as string).getTime() - new Date(b.due_at as string).getTime());

  const meals = (week.data?.slots ?? [])
    .filter((s) => s.day_of_week === dow && (s.recipe_title || s.free_text))
    .sort((a, b) => SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot]);

  const agenda = (events.data ?? [])
    .slice()
    .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime());

  const more = (total: number) =>
    total > MAX_ROWS ? (
      <li className="text-sm text-stein-text">{i18n._("today.more", { count: total - MAX_ROWS })}</li>
    ) : null;

  if (sessionLoading || session === null) return <LoadingState />;

  return (
    <section aria-labelledby="today-heading" className="space-y-6">
      {/* Cinematic hero: a calm silhouette landscape with the date + „Heute" (ADR-0075). */}
      <div className="relative overflow-hidden rounded-card border border-stein/15 shadow-soft">
        <div className="relative h-40 sm:h-48">
          <LandscapeScene className="absolute inset-0 size-full" />
          <div className="scrim-b absolute inset-0" />
          <div className="absolute inset-x-0 bottom-0 p-5 text-tinte dark:text-kalk">
            <p className="text-xs uppercase tracking-wide text-stein-text">{dateLabel}</p>
            <h1 id="today-heading" className="font-display text-3xl font-semibold tracking-tight">
              <Trans id="today.title" />
            </h1>
          </div>
        </div>
      </div>

      {/* First-run quick-start (P8-S2) surfaced on the daily home for an empty household's admin. */}
      {showOnboarding ? <OnboardingPresets /> : null}

      {/* Quiet install hint (ADR-0078): from the third visit, dismissible for good — kein Nag. */}
      <InstallHintCard />

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Tasks due today / overdue */}
        <DashboardTile
          title={<Trans id="today.tasks" />}
          to="/tasks"
          isLoading={tasks.isLoading}
          isError={tasks.isError}
          isEmpty={dueTasks.length === 0}
          emptyText={<Trans id="today.tasks.empty" />}
        >
          <ul className="space-y-1">
            {dueTasks.slice(0, MAX_ROWS).map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-tinte dark:text-kalk">{task.title}</span>
                <span className="shrink-0 text-stein-text">
                  {i18n._("today.points.value", { count: task.points })}
                </span>
              </li>
            ))}
            {more(dueTasks.length)}
          </ul>
        </DashboardTile>

        {/* Today's meals */}
        <DashboardTile
          title={<Trans id="today.meals" />}
          to="/mealplan"
          isLoading={week.isLoading}
          isError={week.isError}
          isEmpty={meals.length === 0}
          emptyText={<Trans id="today.meals.empty" />}
        >
          <ul className="space-y-1">
            {meals.map((slot) => (
              <li key={slot.slot} className="flex items-baseline gap-2 text-sm">
                <span className="w-20 shrink-0 text-xs uppercase tracking-wide text-stein-text">
                  <Trans id={`mealplan.slot.${slot.slot}`} />
                </span>
                <span className="truncate text-tinte dark:text-kalk">{slot.recipe_title ?? slot.free_text}</span>
              </li>
            ))}
          </ul>
        </DashboardTile>

        {/* Today's agenda */}
        <DashboardTile
          title={<Trans id="today.events" />}
          to="/calendar"
          isLoading={events.isLoading}
          isError={events.isError}
          isEmpty={agenda.length === 0}
          emptyText={<Trans id="today.events.empty" />}
        >
          <ul className="space-y-1">
            {agenda.slice(0, MAX_ROWS).map((event) => (
              <li key={`${event.id}-${event.starts_at}`} className="flex items-baseline gap-2 text-sm">
                <span className="w-20 shrink-0 text-stein-text">
                  {event.all_day ? <Trans id="today.events.allDay" /> : formatTime(event.starts_at)}
                </span>
                <span className="truncate text-tinte dark:text-kalk">{event.title}</span>
              </li>
            ))}
            {more(agenda.length)}
          </ul>
        </DashboardTile>

        {/* Open shopping items */}
        <DashboardTile
          title={<Trans id="today.shopping" />}
          to="/shopping"
          isLoading={openCount.isLoading}
          isError={openCount.isError}
          isEmpty={(openCount.data ?? 0) === 0}
          emptyText={<Trans id="today.shopping.empty" />}
        >
          <p className="text-sm text-tinte dark:text-kalk">
            {i18n._("today.shopping.openCount", { count: openCount.data ?? 0 })}
          </p>
        </DashboardTile>

        {/* Points balance */}
        <DashboardTile
          title={<Trans id="today.points" />}
          to="/rewards"
          isLoading={balance.isLoading}
          isError={balance.isError}
          isEmpty={false}
        >
          <p className="font-mono text-2xl tabular-nums text-tinte dark:text-kalk">
            {i18n._("today.points.value", { count: balance.data?.balance ?? 0 })}
          </p>
        </DashboardTile>

        {/* Pinned notes */}
        <DashboardTile
          title={<Trans id="today.pinnedNotes" />}
          to="/notes"
          isLoading={pinned.isLoading}
          isError={pinned.isError}
          isEmpty={(pinned.data?.length ?? 0) === 0}
          emptyText={<Trans id="today.pinnedNotes.empty" />}
        >
          <ul className="space-y-1">
            {pinned.data?.slice(0, MAX_ROWS).map((note) => (
              <li key={note.id}>
                <Link
                  to="/notes"
                  className="flex items-center gap-2 text-sm text-tinte hover:underline dark:text-kalk"
                >
                  <Pin
                    className="size-4 shrink-0 text-laurus dark:text-laurus-dark"
                    aria-hidden="true"
                  />
                  <span className="truncate">{note.title}</span>
                </Link>
              </li>
            ))}
            {more(pinned.data?.length ?? 0)}
          </ul>
        </DashboardTile>
      </div>
    </section>
  );
}
