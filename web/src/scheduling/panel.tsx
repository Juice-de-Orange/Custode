import { Trans } from "@lingui/react";
import { type FormEvent, useEffect, useState } from "react";

import { useCreateEvent } from "../calendar/queries";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { i18n } from "../i18n";
import { PLAN_INTENT_KEY } from "../shopping/ready";
import { useSuggestSlots } from "./queries";

// Scheduling panel (KONZEPT §5.12): suggest conflict-free slots for a task and let the user opt in
// by creating a calendar event from a slot. Read-only suggestions; the entry is explicit.
const REASON_LABELS: Record<string, string> = {
  no_conflict: "scheduling.reasonNoConflict",
  within_work_hours: "scheduling.reasonWorkHours",
  avoids_absence: "scheduling.reasonAvoidsAbsence",
  rain_warning: "scheduling.reasonRainWarning",
  // Synergie S-14: only ever the viewer's OWN wearable reading, only on long tasks.
  low_recovery: "scheduling.reasonLowRecovery",
};

function reasonText(reasons: string[]): string {
  return reasons
    .map((r) => (REASON_LABELS[r] ? i18n._(REASON_LABELS[r]) : r))
    .join(" · ");
}

function formatSlot(startsAt: string, endsAt: string): string {
  const start = new Date(startsAt);
  const end = new Date(endsAt);
  const day = start.toLocaleDateString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `${day} · ${t(start)}–${t(end)}`;
}

export function SchedulingPanel() {
  const suggest = useSuggestSlots();
  const create = useCreateEvent();
  const [title, setTitle] = useState("");
  const [durationMin, setDurationMin] = useState(60);
  const [placed, setPlaced] = useState<string | null>(null);

  // A shopping-list nudge (S-17) can hand off an intent to prefill this panel once on arrival.
  useEffect(() => {
    if (sessionStorage.getItem(PLAN_INTENT_KEY) === "shopping") {
      sessionStorage.removeItem(PLAN_INTENT_KEY);
      setTitle(i18n._("scheduling.shoppingTitle"));
      setDurationMin(45);
    }
  }, []);

  const find = (e: FormEvent) => {
    e.preventDefault();
    setPlaced(null);
    const from = new Date();
    const to = new Date(from.getTime() + 14 * 24 * 3600 * 1000); // next two weeks
    suggest.mutate({ from: from.toISOString(), to: to.toISOString(), durationMin });
  };

  const place = (startsAt: string, endsAt: string) => {
    create.mutate(
      {
        title: title.trim() || i18n._("scheduling.defaultTitle"),
        starts_at: startsAt,
        ends_at: endsAt,
        layer: "household",
      },
      { onSuccess: () => setPlaced(startsAt) },
    );
  };

  return (
    <section
      aria-labelledby="scheduling-heading"
      className="space-y-3 rounded-lg border border-stein/30 p-4"
    >
      <h2 id="scheduling-heading" className="font-display text-lg">
        <Trans id="scheduling.section" />
      </h2>
      <form onSubmit={find} className="flex flex-wrap items-end gap-3">
        <Field
          id="sch-title"
          label={<Trans id="scheduling.title" />}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="min-w-44"
        />
        <div className="space-y-1">
          <label htmlFor="sch-duration" className="block text-sm font-medium text-tinte dark:text-kalk">
            <Trans id="scheduling.duration" />
          </label>
          <select
            id="sch-duration"
            value={durationMin}
            onChange={(e) => setDurationMin(Number(e.target.value))}
            className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
          >
            <option value={30}>30 min</option>
            <option value={60}>60 min</option>
            <option value={90}>90 min</option>
            <option value={120}>120 min</option>
          </select>
        </div>
        <Button type="submit" disabled={suggest.isPending}>
          <Trans id="scheduling.find" />
        </Button>
      </form>

      {suggest.isPending ? (
        <p className="text-sm text-stein-text">…</p>
      ) : suggest.data && suggest.data.length > 0 ? (
        <ul className="space-y-2">
          {suggest.data.map((slot) => (
            <li
              key={slot.start}
              className="flex items-center justify-between gap-4 rounded-md bg-stein/10 px-3 py-2"
            >
              <span className="text-sm text-tinte dark:text-kalk">
                {formatSlot(slot.start, slot.end)}
                <span className="ml-2 text-stein-text">{reasonText(slot.reasons)}</span>
              </span>
              {placed === slot.start ? (
                <span className="text-sm text-laurus dark:text-laurus-dark">
                  <Trans id="scheduling.placed" />
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => place(slot.start, slot.end)}
                  disabled={create.isPending}
                  className="text-sm text-laurus dark:text-laurus-dark hover:underline"
                >
                  <Trans id="scheduling.place" />
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : suggest.data ? (
        <p className="text-sm text-stein-text">
          <Trans id="scheduling.none" />
        </p>
      ) : null}
    </section>
  );
}
