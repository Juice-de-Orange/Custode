import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  NoteCreate,
  NoteResponse,
  NoteSummary,
  NoteUpdate,
  NoteVersionResponse,
  ToTaskResult,
  TrashedNote,
} from "../api/types.gen";
import { toProblem } from "../auth/session";
import { TASKS_QUERY_KEY } from "../tasks/queries";

// A note plus its ETag (the row version) so a PATCH can send If-Match (ADR-0029); 412 = stale.
export type NoteWithEtag = NoteResponse & { etag: string };

function withEtag(data: unknown, response: Response | undefined): NoteWithEtag {
  return { ...(data as NoteResponse), etag: response?.headers.get("etag") ?? "" };
}

export const NOTES_QUERY_KEY = ["notes"] as const;

async function fetchNotes(): Promise<NoteSummary[]> {
  const { data, error, response } = await client.get({ url: "/v1/notes" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as NoteSummary[];
}

async function fetchPinnedNotes(): Promise<NoteSummary[]> {
  const { data, error, response } = await client.get({
    url: "/v1/notes",
    query: { pinned: true },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as NoteSummary[];
}

async function fetchNote(id: string): Promise<NoteWithEtag> {
  const { data, error, response } = await client.get({ url: `/v1/notes/${id}` });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function postNote(body: NoteCreate): Promise<NoteWithEtag> {
  const { data, error, response } = await client.post({ url: "/v1/notes", body });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function patchNote(vars: {
  id: string;
  update: NoteUpdate;
  etag: string;
}): Promise<NoteWithEtag> {
  const { data, error, response } = await client.patch({
    url: `/v1/notes/${vars.id}`,
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function deleteNote(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/notes/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export function useNotes() {
  return useQuery({ queryKey: NOTES_QUERY_KEY, queryFn: fetchNotes });
}

// Pinned notes for the „Heute" dashboard tile (P7-S10). Shares the notes query key so any
// note change (pin toggle, edit, delete) refreshes the tile live via the realtime map.
export function usePinnedNotes() {
  return useQuery({ queryKey: [...NOTES_QUERY_KEY, "pinned"], queryFn: fetchPinnedNotes });
}

export function useNote(id: string | null) {
  return useQuery({
    queryKey: [...NOTES_QUERY_KEY, id],
    queryFn: () => fetchNote(id as string),
    enabled: id !== null,
  });
}

function useNotesMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: NOTES_QUERY_KEY }),
  });
}

export function useCreateNote() {
  return useNotesMutation(postNote);
}

export function useUpdateNote() {
  return useNotesMutation(patchNote);
}

export function useDeleteNote() {
  return useNotesMutation(deleteNote);
}

async function fetchTrashedNotes(): Promise<TrashedNote[]> {
  const { data, error, response } = await client.get({ url: "/v1/notes/trash" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as TrashedNote[];
}

// The trash shares the notes query key, so restoring (or the reaper, via SSE) refreshes it live.
export function useTrashedNotes() {
  return useQuery({ queryKey: [...NOTES_QUERY_KEY, "trash"], queryFn: fetchTrashedNotes });
}

async function untrashNote(id: string): Promise<void> {
  const { error, response } = await client.post({ url: `/v1/notes/${id}/untrash` });
  if (error) throw toProblem(error, response?.status);
}

export function useUntrashNote() {
  return useNotesMutation(untrashNote);
}

async function fetchVersions(id: string): Promise<NoteVersionResponse[]> {
  const { data, error, response } = await client.get({ url: `/v1/notes/${id}/versions` });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as NoteVersionResponse[];
}

export function useNoteVersions(id: string | null) {
  return useQuery({
    queryKey: [...NOTES_QUERY_KEY, id, "versions"],
    queryFn: () => fetchVersions(id as string),
    enabled: id !== null,
  });
}

async function restoreVersion(vars: { id: string; versionNo: number }): Promise<void> {
  const { error, response } = await client.post({
    url: `/v1/notes/${vars.id}/restore`,
    query: { version_no: vars.versionNo },
  });
  if (error) throw toProblem(error, response?.status);
}

export function useRestoreVersion() {
  return useNotesMutation(restoreVersion);
}

async function convertToTask(id: string): Promise<ToTaskResult> {
  const { data, error, response } = await client.post({ url: `/v1/notes/${id}/to-task` });
  if (error) throw toProblem(error, response?.status);
  return data as ToTaskResult;
}

export function useConvertToTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: convertToTask,
    // The new task lands in the tasks module -> refresh task views.
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}
