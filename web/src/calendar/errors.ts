// CalDAV/write-back problem slugs -> catalog message refs (P9 Web-Abo-Verwaltung). One central
// map instead of scattered slug comparisons; rendered via <Trans id={msg.id} values={msg.values}>.

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";

export type MessageRef = { id: string; values?: Record<string, string> };

const SYNC_CATEGORIES = new Set([
  "auth_failed",
  "unreachable",
  "not_calendar",
  "invalid_response",
  "too_large",
  "blocked_url",
  "conflict",
  "crypto_unconfigured",
  "creds_undecryptable",
  "sync_disabled",
]);

/** ``last_sync_error`` category -> catalog id (also used by the status line). */
export function syncErrorId(category: string): string {
  return SYNC_CATEGORIES.has(category)
    ? `calendar.subs.sync.${category}`
    : "calendar.subs.sync.failed";
}

const SLUG_MESSAGES: Record<string, string> = {
  external_conflict: "calendar.err.externalConflict",
  external_event_read_only: "calendar.err.externalReadOnly",
  external_not_synced: "calendar.err.notSynced",
  caldav_disabled: "calendar.subs.sync.sync_disabled",
  crypto_unconfigured: "calendar.subs.sync.crypto_unconfigured",
  subscription_exists: "calendar.subs.err.exists",
  precondition_failed: "calendar.subs.err.conflict",
  external_kind_unsupported: "calendar.err.externalCreateUnsupported",
  external_tzid_unsupported: "calendar.err.externalCreateUnsupported",
  invalid_range: "calendar.err.endBeforeStart",
  not_found: "calendar.err.notSynced",
};

/** Problem -> user message for the calendar create/edit/delete and subscription flows. */
export function calendarProblemMessage(err: unknown): MessageRef {
  if (!(err instanceof ProblemError)) return { id: "state.error" };
  if (err.slug === "external_field_readonly") {
    return { id: "calendar.err.fieldReadonly", values: { field: String(err.extra.field ?? "") } };
  }
  if (err.slug === "caldav_write_failed") {
    const category = String(err.extra.category ?? "");
    return { id: "calendar.err.writeFailed", values: { category: i18n._(syncErrorId(category)) } };
  }
  return { id: SLUG_MESSAGES[err.slug] ?? "state.error" };
}
