// Subject-rights download (Art. 15 Auskunft, Art. 20 Portabilität). Two routes, one mechanism:
// ``/v1/me/export`` is what is attributable to the calling person (any role, including a child),
// ``/v1/household/export`` is the shared household record (admin only). Neither widens what the
// caller may see — the server runs both on the caller's own RLS-scoped session.
//
// This is the only place in the web that asks the generated client for a **blob**: the routes
// answer ``application/zip``, not JSON. The generated client handles that fine (it parses errors
// as text/JSON regardless of ``parseAs``), so the auth interceptor — cookie, CSRF, silent 401
// refresh — still applies; a raw ``fetch`` would have to re-implement all three.
//
// Deliberately a mutation, not a query: the archive is built per request and never cached. A
// TanStack query would refetch on focus and silently drop a second copy of somebody's personal
// data into their download folder.

import { useMutation } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import { toProblem } from "../lib/problem";

export const EXPORT_SCOPES = ["me", "household"] as const;
export type ExportScope = (typeof EXPORT_SCOPES)[number];

const URLS: Record<ExportScope, string> = {
  me: "/v1/me/export",
  household: "/v1/household/export",
};

/** Strip anything that would make a server-supplied name behave like a path.
 *
 *  The name lands on the file system of whoever clicked, so it is not merely a label. The server
 *  builds it itself today; this guards the *next* code path that writes a Content-Disposition. */
export function safeFilename(candidate: string, fallback: string): string {
  const base = candidate.replace(/\\/g, "/").split("/").pop() ?? "";
  // eslint-disable-next-line no-control-regex -- C0/DEL are exactly what must not survive
  const cleaned = base.replace(/[\u0000-\u001f\u007f"]/g, "").trim();
  return cleaned && cleaned !== "." && cleaned !== ".." ? cleaned : fallback;
}

/** ``Content-Disposition`` -> file name, in both the plain and the RFC-5987 (``filename*``)
 *  form. Anything missing or unparseable falls back to a name we build ourselves, so the
 *  download is never called ``download``. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const extended = /filename\*\s*=\s*[^']*'[^']*'([^;]+)/i.exec(header);
  if (extended) {
    try {
      return safeFilename(decodeURIComponent(extended[1].trim()), fallback);
    } catch {
      // Malformed percent-escape — fall through to the plain form rather than failing the save.
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/i.exec(header);
  const raw = plain?.[1] ?? plain?.[2];
  return raw ? safeFilename(raw.trim(), fallback) : fallback;
}

/** Mirrors the server's own name (``kernel/http/export.py``). ``custode`` here is the TECHNICAL
 *  project name — repo, package, DB, bucket — not the marketing name, which only ever renders
 *  through ``BRAND_NAME`` (CLAUDE.md). */
export function fallbackFilename(scope: ExportScope, now: Date = new Date()): string {
  const day = now.toISOString().slice(0, 10);
  return `custode-export-${scope === "me" ? "personal" : "household"}-${day}.zip`;
}

/** Hand the archive to the browser. Separate from the request so the parsing above stays
 *  testable without a DOM, and so the object URL is revoked in exactly one place: a live object
 *  URL pins the whole archive — personal data — in memory for the lifetime of the document. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Next tick, not immediately: some browsers abort the save when the URL dies in the same task.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Fetch the archive and save it. Answers the file name so the UI can name what it just did. */
export async function downloadExport(scope: ExportScope): Promise<string> {
  const { data, error, response } = await client.get({ url: URLS[scope], parseAs: "blob" });
  if (error) throw toProblem(error, response?.status);
  const filename = filenameFromDisposition(
    response?.headers.get("Content-Disposition") ?? null,
    fallbackFilename(scope),
  );
  saveBlob(data as Blob, filename);
  return filename;
}

/** No retry: a failed export must not quietly make the server build a multi-MB archive again. */
export function useExportDownload() {
  return useMutation({ mutationFn: downloadExport, retry: false });
}
