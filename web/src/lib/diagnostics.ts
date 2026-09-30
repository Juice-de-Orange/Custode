import type { DiagnosticEntry, FeedbackDiagnostics } from "../api/types.gen";

// Client diagnostics ring buffer (KONZEPT §5.12). Captures a small, bounded trail of **technical
// breadcrumbs only** — the route the user was on, the error-reference short-code (ARCHITECTURE
// §12) and HTTP status — so a feedback report can optionally carry support context. It deliberately
// stores **no message bodies, form values, or other content/PII**: only the fields below.
//
// The attachment is strictly opt-in per report (the feedback form's checkbox); this module merely
// collects breadcrumbs in memory. Nothing is persisted or sent unless the user ticks the box.

// Build-injectable app version (Vite define); falls back to "dev" when unset.
export const APP_VERSION: string = import.meta.env.VITE_APP_VERSION ?? "dev";

const MAX_ENTRIES = 25;
const buffer: DiagnosticEntry[] = [];

export function recordDiagnostic(entry: Omit<DiagnosticEntry, "at">): void {
  buffer.push({ at: new Date().toISOString(), ...entry });
  if (buffer.length > MAX_ENTRIES) buffer.splice(0, buffer.length - MAX_ENTRIES);
}

// A snapshot for attaching to a feedback submission (newest entries kept, capped).
export function getDiagnostics(): FeedbackDiagnostics {
  return { app_version: APP_VERSION, entries: [...buffer] };
}

// Test/seam helper.
export function clearDiagnostics(): void {
  buffer.length = 0;
}
