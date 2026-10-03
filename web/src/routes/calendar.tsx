import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { Repeat } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import type { EventResponse } from "../api/types.gen";
import { useSession } from "../auth/session";
import { calendarProblemMessage, type MessageRef } from "../calendar/errors";
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
import { SubscriptionsSection } from "../calendar/subscriptions-section";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { flagEnabled } from "../lib/flags";
import { SchedulingPanel } from "../scheduling/panel";
import { WeatherCard } from "../weather/card";

// Calendar (KONZEPT §5.11): personal + household events. Agenda list + a create form. The
// household layer is shared with all members; the personal layer stays private to its owner.
function formatRange(startsAt: string, endsAt: string, allDay: boolean): string {
  const start = new Date(startsAt);
  const end = new Date(endsAt);
  const day = start.toLocaleDateString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
  if (allDay) return `${day} · ${i18n._("calendar.allDay")}`;
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `${day} · ${t(start)}–${t(end)}`;
}

// An ISO-UTC instant -> a "YYYY-MM-DDTHH:mm" value for a datetime-local input (in local time).
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function CalendarPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const events = useEvents();
  const create = useCreateEvent();
  const remove = useDeleteEvent();
  const cancelOccurrence = useCancelOccurrence();
  const moveOccurrence = useMoveOccurrence();
  const createFeed = useCreateFeed();
  const deleteFeed = useDeleteFeed();
  const importIcs = useImportIcs();
  const subs = useSubscriptions();
  const [feedUrl, setFeedUrl] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [createError, setCreateError] = useState<MessageRef | null>(null);
  // End before start: said at the field it concerns, before the request — the server's answer to
  // it is a plain validation 422, which would only surface as the generic message.
  const [endError, setEndError] = useState(false);
  const [agendaError, setAgendaError] = useState<MessageRef | null>(null);
  // The occurrence currently being moved (its original_start) + the new start the user picked.
  const [movingKey, setMovingKey] = useState<string | null>(null);
  const [moveStart, setMoveStart] = useState("");

  const [title, setTitle] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [personal, setPersonal] = useState(false);
  const [allDay, setAllDay] = useState(false);
  const [repeat, setRepeat] = useState<"none" | "daily" | "weekly" | "monthly">("none");
  const [kind, setKind] = useState<"normal" | "absence" | "guest">("normal");
  // "" = the Custode calendar (behaviour as before); a subscription id = create the event in
  // the external CalDAV calendar (write-through, P9-S4).
  const [target, setTarget] = useState("");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  const me = session.user_id;

  const RRULE: Record<string, string | null> = {
    none: null,
    daily: "FREQ=DAILY",
    weekly: "FREQ=WEEKLY",
    monthly: "FREQ=MONTHLY",
  };

  const submitMove = (ev: EventResponse) => {
    if (!ev.original_start || !moveStart) return;
    const durationMs = new Date(ev.ends_at).getTime() - new Date(ev.starts_at).getTime();
    const newStart = new Date(moveStart);
    const newEnd = new Date(newStart.getTime() + durationMs);
    moveOccurrence.mutate(
      {
        seriesId: ev.series_id,
        occurrenceStart: ev.original_start,
        newStart: newStart.toISOString(),
        newEnd: newEnd.toISOString(),
      },
      { onSuccess: () => setMovingKey(null) },
    );
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !startsAt || !endsAt) return;
    setCreateError(null);
    if (new Date(endsAt).getTime() < new Date(startsAt).getTime()) {
      setEndError(true);
      return;
    }
    setEndError(false);
    const base = {
      title: title.trim(),
      starts_at: new Date(startsAt).toISOString(),
      ends_at: new Date(endsAt).toISOString(),
      all_day: allDay,
      rrule: RRULE[repeat],
    };
    const payload = target
      ? {
          ...base,
          // The external target requires UTC anchoring and a plain personal event — the
          // backend 422s anything else (ADR-0080 E5/E6); never send the browser zone here.
          layer: "personal" as const,
          kind: "normal" as const,
          tzid: "UTC",
          subscription_id: target,
        }
      : {
          ...base,
          layer: personal ? ("personal" as const) : ("household" as const),
          kind,
          // Anchor recurring events in the user's zone so they stay DST-correct (P5-S9).
          tzid: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        };
    create.mutate(payload, {
      // Reset only on success — a failed create must not eat the input (fix vs. pre-P9 code).
      onSuccess: () => {
        setTitle("");
        setStartsAt("");
        setEndsAt("");
        setPersonal(false);
        setAllDay(false);
        setRepeat("none");
        setKind("normal");
        setTarget("");
      },
      onError: (err) => setCreateError(calendarProblemMessage(err)),
    });
  };

  const handleImport = async (event: FormEvent) => {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const content = await file.text();
    input.value = ""; // allow re-selecting the same file
    importIcs.mutate(
      { content, layer: personal ? "personal" : "household" },
      {
        onSuccess: (r) =>
          setImportMsg(
            i18n._("calendar.importDone", {
              imported: r.imported,
              skipped: r.skipped,
              failed: r.failed,
            }),
          ),
        onError: () => setImportMsg(i18n._("calendar.importError")),
      },
    );
  };

  return (
    <section aria-labelledby="calendar-heading" className="space-y-8">
      <h1 id="calendar-heading" className="font-display text-2xl">
        <Trans id="calendar.section" />
      </h1>

      {flagEnabled(session.flags, "weather") ? (
        <WeatherCard isAdmin={session.role === "admin"} />
      ) : null}

      <SchedulingPanel />

      {/* Create form */}
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <Field
          id="ev-title"
          label={<Trans id="calendar.title" />}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="min-w-48"
        />
        <Field
          id="ev-start"
          type="datetime-local"
          label={<Trans id="calendar.start" />}
          value={startsAt}
          onChange={(e) => {
            setStartsAt(e.target.value);
            setEndError(false);
          }}
        />
        <div className="space-y-1">
          <Field
            id="ev-end"
            type="datetime-local"
            label={<Trans id="calendar.end" />}
            value={endsAt}
            onChange={(e) => {
              setEndsAt(e.target.value);
              setEndError(false);
            }}
            aria-invalid={endError ? true : undefined}
            aria-describedby={endError ? "ev-end-error" : undefined}
          />
          {endError ? (
            <p id="ev-end-error" role="alert" className="text-sm text-rost dark:text-bernstein">
              <Trans id="calendar.err.endBeforeStart" />
            </p>
          ) : null}
        </div>
        <label className="flex items-center gap-2 py-2 text-sm text-tinte dark:text-kalk">
          <input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} />
          <Trans id="calendar.allDay" />
        </label>
        <label className="flex items-center gap-2 py-2 text-sm text-tinte dark:text-kalk">
          <input
            type="checkbox"
            checked={target ? true : personal}
            disabled={!!target}
            onChange={(e) => setPersonal(e.target.checked)}
          />
          <Trans id="calendar.personal" />
        </label>
        {subs.data && subs.data.length > 0 ? (
          <div className="space-y-1">
            <label
              htmlFor="ev-target"
              className="block text-sm font-medium text-tinte dark:text-kalk"
            >
              <Trans id="calendar.target" />
            </label>
            <select
              id="ev-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            >
              <option value="">{i18n._("calendar.targetDefault")}</option>
              {subs.data.map((sub) => (
                <option key={sub.id} value={sub.id}>
                  {sub.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="space-y-1">
          <label htmlFor="ev-repeat" className="block text-sm font-medium text-tinte dark:text-kalk">
            <Trans id="calendar.repeat" />
          </label>
          <select
            id="ev-repeat"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value as typeof repeat)}
            className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
          >
            <option value="none">{i18n._("calendar.repeatNone")}</option>
            <option value="daily">{i18n._("calendar.repeatDaily")}</option>
            <option value="weekly">{i18n._("calendar.repeatWeekly")}</option>
            <option value="monthly">{i18n._("calendar.repeatMonthly")}</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="ev-kind" className="block text-sm font-medium text-tinte dark:text-kalk">
            <Trans id="calendar.kind" />
          </label>
          <select
            id="ev-kind"
            value={target ? "normal" : kind}
            disabled={!!target}
            onChange={(e) => setKind(e.target.value as typeof kind)}
            className="block rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
          >
            <option value="normal">{i18n._("calendar.kindNormal")}</option>
            <option value="absence">{i18n._("calendar.kindAbsence")}</option>
            <option value="guest">{i18n._("calendar.kindGuest")}</option>
          </select>
        </div>
        <Button type="submit" disabled={create.isPending || !title.trim()}>
          <Trans id="calendar.add" />
        </Button>
        {target ? (
          <p className="w-full text-sm text-stein-text">
            <Trans id="calendar.externalCreateHint" />
          </p>
        ) : null}
        {createError ? (
          <p role="alert" className="w-full text-sm text-rost dark:text-bernstein">
            <Trans id={createError.id} values={createError.values} />
          </p>
        ) : null}
      </form>

      {/* Agenda */}
      {agendaError ? (
        <p role="alert" className="text-sm text-rost dark:text-bernstein">
          <Trans id={agendaError.id} values={agendaError.values} />
        </p>
      ) : null}
      {events.isLoading ? (
        <LoadingState />
      ) : events.isError ? (
        <ErrorState />
      ) : events.data && events.data.length > 0 ? (
        <ul className="space-y-3">
          {events.data.map((ev) => (
            <li
              key={`${ev.series_id}-${ev.starts_at}`}
              className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 p-4"
            >
              <div>
                <span className="font-display text-lg text-tinte dark:text-kalk">
                  {ev.title}
                  {ev.recurring ? (
                    <span className="ml-2 text-sm text-laurus dark:text-laurus-dark">
                      <Repeat className="size-4" aria-hidden="true" />
                    </span>
                  ) : null}
                  {ev.kind !== "normal" ? (
                    <span className="ml-2 rounded-full bg-stein/15 px-2 py-0.5 text-xs uppercase tracking-wide text-stein-text">
                      {i18n._(ev.kind === "absence" ? "calendar.kindAbsence" : "calendar.kindGuest")}
                    </span>
                  ) : null}
                  {ev.external ? (
                    <span className="ml-2 rounded-full bg-stein/15 px-2 py-0.5 text-xs uppercase tracking-wide text-stein-text">
                      {i18n._("calendar.externalBadge")}
                    </span>
                  ) : null}
                </span>
                <span className="mt-1 block text-sm text-stein-text">
                  {formatRange(ev.starts_at, ev.ends_at, ev.all_day)}
                  {ev.layer === "personal" ? (
                    <>
                      {" · "}
                      <span className="text-laurus dark:text-laurus-dark">
                        <Trans id="calendar.personal" />
                      </span>
                    </>
                  ) : null}
                  {ev.location ? ` · ${ev.location}` : null}
                </span>
              </div>
              {ev.owner_id === me ? (
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {/* Occurrence actions stay off for mirrors — overrides aren't synced back
                      (ADR-0080 §7, the backend answers 409). */}
                  {ev.recurring && ev.original_start && !ev.external ? (
                    <>
                      {movingKey === ev.original_start ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="datetime-local"
                            value={moveStart}
                            onChange={(e) => setMoveStart(e.target.value)}
                            className="rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
                          />
                          <button
                            type="button"
                            onClick={() => submitMove(ev)}
                            disabled={moveOccurrence.isPending || !moveStart}
                            className="text-sm text-laurus dark:text-laurus-dark hover:underline"
                          >
                            <Trans id="calendar.moveConfirm" />
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setMovingKey(ev.original_start);
                            setMoveStart(toLocalInput(ev.starts_at));
                          }}
                          className="text-sm text-stein-text hover:underline"
                        >
                          <Trans id="calendar.move" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() =>
                          cancelOccurrence.mutate({
                            seriesId: ev.series_id,
                            occurrenceStart: ev.original_start ?? ev.starts_at,
                          })
                        }
                        disabled={cancelOccurrence.isPending}
                        className="text-sm text-stein-text hover:underline"
                      >
                        <Trans id="calendar.cancelOccurrence" />
                      </button>
                    </>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => {
                      // Deleting a mirror deletes the event in the EXTERNAL calendar too —
                      // that deserves a confirm; local deletes stay one-click as before.
                      if (ev.external && !window.confirm(i18n._("calendar.confirmDeleteExternal"))) {
                        return;
                      }
                      setAgendaError(null);
                      remove.mutate(ev.id, {
                        onError: (err) => setAgendaError(calendarProblemMessage(err)),
                      });
                    }}
                    disabled={remove.isPending}
                    className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                  >
                    <Trans id="calendar.delete" />
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState>
          <Trans id="calendar.empty" />
        </EmptyState>
      )}

      {/* ICS subscription feed: a secret URL to subscribe in Google/Nextcloud/Apple. */}
      <section aria-labelledby="feed-heading" className="space-y-3 border-t border-stein/20 pt-6">
        <h2 id="feed-heading" className="font-display text-lg">
          <Trans id="calendar.feed" />
        </h2>
        <p className="text-sm text-stein-text">
          <Trans id="calendar.feedHint" />
        </p>
        {feedUrl ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              readOnly
              value={feedUrl}
              onFocus={(e) => e.target.select()}
              className="min-w-72 flex-1 rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-sm text-tinte dark:text-kalk"
            />
            <button
              type="button"
              onClick={() => {
                deleteFeed.mutate(undefined, { onSuccess: () => setFeedUrl(null) });
              }}
              className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
            >
              <Trans id="calendar.feedRevoke" />
            </button>
          </div>
        ) : (
          <Button
            onClick={() =>
              createFeed.mutate(undefined, { onSuccess: (f) => setFeedUrl(f.url) })
            }
            disabled={createFeed.isPending}
          >
            <Trans id="calendar.feedGenerate" />
          </Button>
        )}
      </section>

      {/* ICS import: upload a .ics file exported from another calendar (no URL fetch — no SSRF). */}
      <section
        aria-labelledby="import-heading"
        className="space-y-3 border-t border-stein/20 pt-6"
      >
        <h2 id="import-heading" className="font-display text-lg">
          <Trans id="calendar.import" />
        </h2>
        <p className="text-sm text-stein-text">
          <Trans id="calendar.importHint" />
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-sm text-tinte dark:text-kalk hover:border-laurus">
          <Trans id="calendar.importPick" />
          <input
            type="file"
            accept=".ics,text/calendar"
            className="sr-only"
            disabled={importIcs.isPending}
            onChange={(e) => {
              void handleImport(e);
            }}
          />
        </label>
        {importMsg ? (
          <p className="text-sm text-laurus dark:text-laurus-dark" role="status">
            {importMsg}
          </p>
        ) : null}
      </section>

      {/* External CalDAV subscriptions (P9, Web-Abo-Verwaltung). */}
      <SubscriptionsSection />
    </section>
  );
}
