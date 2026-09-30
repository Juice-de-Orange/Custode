import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  EventCreate,
  EventResponse,
  FeedResponse,
  IcsImportRequest,
  IcsImportResult,
  SubscriptionCreate,
  SubscriptionResponse,
  SubscriptionUpdate,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

async function fetchEvents(range?: { from: string; to: string }): Promise<EventResponse[]> {
  const { data, error, response } = await client.get({
    url: "/v1/calendar/events",
    ...(range ? { query: { from: range.from, to: range.to } } : {}),
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as EventResponse[];
}

async function postEvent(body: EventCreate): Promise<EventResponse> {
  const { data, error, response } = await client.post({ url: "/v1/calendar/events", body });
  if (error) throw toProblem(error, response?.status);
  return data as EventResponse;
}

async function deleteEvent(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/calendar/events/${id}` });
  if (error) throw toProblem(error, response?.status);
}

type OccurrenceVars = { seriesId: string; occurrenceStart: string };

async function cancelOccurrence({ seriesId, occurrenceStart }: OccurrenceVars): Promise<void> {
  const { error, response } = await client.post({
    url: `/v1/calendar/events/${seriesId}/cancel-occurrence`,
    body: { occurrence_start: occurrenceStart },
  });
  if (error) throw toProblem(error, response?.status);
}

type MoveVars = { seriesId: string; occurrenceStart: string; newStart: string; newEnd: string };

async function moveOccurrence({
  seriesId,
  occurrenceStart,
  newStart,
  newEnd,
}: MoveVars): Promise<void> {
  const { error, response } = await client.post({
    url: `/v1/calendar/events/${seriesId}/move-occurrence`,
    body: { occurrence_start: occurrenceStart, new_start: newStart, new_end: newEnd },
  });
  if (error) throw toProblem(error, response?.status);
}

export const CALENDAR_QUERY_KEY = ["calendar"] as const;

export function useEvents() {
  return useQuery({ queryKey: CALENDAR_QUERY_KEY, queryFn: () => fetchEvents() });
}

// Today's concrete occurrences for the „Heute" dashboard tile. The server expands recurring
// series within the [from,to) window (calendar/router.py), so this includes daily/weekly repeats.
export function useTodayEvents(range: { from: string; to: string }) {
  return useQuery({
    queryKey: [...CALENDAR_QUERY_KEY, "today", range.from, range.to],
    queryFn: () => fetchEvents(range),
  });
}

function useCalendarMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: CALENDAR_QUERY_KEY }),
  });
}

export function useCreateEvent() {
  return useCalendarMutation(postEvent);
}

export function useDeleteEvent() {
  return useCalendarMutation(deleteEvent);
}

export function useCancelOccurrence() {
  return useCalendarMutation(cancelOccurrence);
}

export function useMoveOccurrence() {
  return useCalendarMutation(moveOccurrence);
}

async function importIcs(body: IcsImportRequest): Promise<IcsImportResult> {
  const { data, error, response } = await client.post({ url: "/v1/calendar/import", body });
  if (error) throw toProblem(error, response?.status);
  return data as IcsImportResult;
}

export function useImportIcs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: importIcs,
    onSuccess: () => qc.invalidateQueries({ queryKey: CALENDAR_QUERY_KEY }),
  });
}

// --- ICS subscription feed ---------------------------------------------------

async function createFeed(): Promise<FeedResponse> {
  const { data, error, response } = await client.post({ url: "/v1/calendar/feed" });
  if (error) throw toProblem(error, response?.status);
  return data as FeedResponse;
}

async function deleteFeed(): Promise<void> {
  const { error, response } = await client.delete({ url: "/v1/calendar/feed" });
  if (error) throw toProblem(error, response?.status);
}

export function useCreateFeed() {
  return useMutation({ mutationFn: createFeed });
}

export function useDeleteFeed() {
  return useMutation({ mutationFn: deleteFeed });
}

// --- External CalDAV subscriptions (P9, Web-Abo-Verwaltung) -------------------
// Keyed under the calendar prefix so the SSE entity "calendar" (which the backend also fires
// for calendar.subscription.* events) invalidates subscriptions for free.

export type SubscriptionWithEtag = SubscriptionResponse & { etag: string };

const SUBSCRIPTIONS_KEY = [...CALENDAR_QUERY_KEY, "subscriptions"] as const;

// The list endpoint carries no ETags — the edit flow fetches the single resource for a fresh
// one (recipes withEtag pattern); the wire never carries credentials (has_credentials only).
function withEtag(data: unknown, response: Response | undefined): SubscriptionWithEtag {
  return { ...(data as SubscriptionResponse), etag: response?.headers.get("etag") ?? "" };
}

async function fetchSubscriptions(): Promise<SubscriptionResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/calendar/subscriptions" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as SubscriptionResponse[];
}

async function fetchSubscription(id: string): Promise<SubscriptionWithEtag> {
  const { data, error, response } = await client.get({
    url: `/v1/calendar/subscriptions/${id}`,
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function postSubscription(body: SubscriptionCreate): Promise<SubscriptionWithEtag> {
  const { data, error, response } = await client.post({
    url: "/v1/calendar/subscriptions",
    body,
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

type SubscriptionPatchVars = { id: string; etag: string; update: SubscriptionUpdate };

async function patchSubscription(vars: SubscriptionPatchVars): Promise<SubscriptionWithEtag> {
  const { data, error, response } = await client.patch({
    url: `/v1/calendar/subscriptions/${vars.id}`,
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

export type CheckResult = { ok: boolean; category: string | null; objects: number | null };

// Probe the stored URL + credentials and answer now, instead of leaving the member to guess
// until the next 15-minute cron tick writes last_sync_error.
async function checkSubscription(id: string): Promise<CheckResult> {
  const { data, error, response } = await client.post({
    url: `/v1/calendar/subscriptions/${id}/check`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as CheckResult;
}

async function deleteSubscription(id: string): Promise<void> {
  const { error, response } = await client.delete({
    url: `/v1/calendar/subscriptions/${id}`,
  });
  if (error) throw toProblem(error, response?.status);
}

// Pause/resume: the list carries no version, so fetch a fresh ETag and patch in one go — the
// same fresh-anchor strategy the write-back itself uses (ADR-0080 E3). Two round-trips for a
// rare, idempotent action.
async function toggleSubscription(vars: { id: string; enabled: boolean }) {
  const current = await fetchSubscription(vars.id);
  return patchSubscription({
    id: vars.id,
    etag: current.etag,
    update: { enabled: vars.enabled },
  });
}

export function useSubscriptions() {
  return useQuery({ queryKey: SUBSCRIPTIONS_KEY, queryFn: fetchSubscriptions });
}

export function useSubscription(id: string | null) {
  return useQuery({
    queryKey: [...SUBSCRIPTIONS_KEY, id],
    queryFn: () => fetchSubscription(id as string),
    enabled: id !== null,
  });
}

export function useCreateSubscription() {
  return useCalendarMutation(postSubscription);
}

export function useUpdateSubscription() {
  return useCalendarMutation(patchSubscription);
}

export function useToggleSubscription() {
  return useCalendarMutation(toggleSubscription);
}

export function useDeleteSubscription() {
  // Deleting a subscription also tombstones its mirrored events — the broad calendar
  // invalidation of useCalendarMutation refreshes the agenda too.
  return useCalendarMutation(deleteSubscription);
}

/** A probe writes nothing, so there is nothing to invalidate — the result is transient UI state. */
export function useCheckSubscription() {
  return useMutation({ mutationFn: checkSubscription });
}
