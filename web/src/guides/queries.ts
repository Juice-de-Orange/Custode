import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  AttachmentResponse,
  GuideCreate,
  GuideResponse,
  GuideSummary,
  GuideUpdate,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

// A guide plus its ETag (the row version) so a PATCH can send If-Match (ADR-0029); 412 = stale.
export type GuideWithEtag = GuideResponse & { etag: string };

function withEtag(data: unknown, response: Response | undefined): GuideWithEtag {
  return { ...(data as GuideResponse), etag: response?.headers.get("etag") ?? "" };
}

export const GUIDES_QUERY_KEY = ["guides"] as const;

async function fetchGuides(q: string): Promise<GuideSummary[]> {
  const { data, error, response } = await client.get({
    url: "/v1/guides",
    query: q.trim() ? { q } : {},
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as GuideSummary[];
}

async function fetchGuide(id: string): Promise<GuideWithEtag> {
  const { data, error, response } = await client.get({ url: `/v1/guides/${id}` });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function postGuide(body: GuideCreate): Promise<GuideWithEtag> {
  const { data, error, response } = await client.post({ url: "/v1/guides", body });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function patchGuide(vars: {
  id: string;
  update: GuideUpdate;
  etag: string;
}): Promise<GuideWithEtag> {
  const { data, error, response } = await client.patch({
    url: `/v1/guides/${vars.id}`,
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function deleteGuide(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/guides/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export function useGuides(q: string) {
  return useQuery({ queryKey: [...GUIDES_QUERY_KEY, q], queryFn: () => fetchGuides(q) });
}

export function useGuide(id: string | null) {
  return useQuery({
    queryKey: [...GUIDES_QUERY_KEY, "one", id],
    queryFn: () => fetchGuide(id as string),
    enabled: id !== null,
  });
}

function useGuidesMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: GUIDES_QUERY_KEY }),
  });
}

// --- Attachments (P7-S22): metadata via the API, bytes streamed from a direct link. ---

async function fetchAttachments(guideId: string): Promise<AttachmentResponse[]> {
  const { data, error, response } = await client.get({
    url: `/v1/guides/${guideId}/attachments`,
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as AttachmentResponse[];
}

async function uploadAttachment(vars: { guideId: string; file: File }): Promise<AttachmentResponse> {
  const form = new FormData();
  form.append("file", vars.file);
  const { data, error, response } = await client.post({
    url: `/v1/guides/${vars.guideId}/attachments`,
    body: form,
  });
  if (error) throw toProblem(error, response?.status);
  return data as AttachmentResponse;
}

async function deleteAttachment(vars: { guideId: string; id: string }): Promise<void> {
  const { error, response } = await client.delete({
    url: `/v1/guides/${vars.guideId}/attachments/${vars.id}`,
  });
  if (error) throw toProblem(error, response?.status);
}

export function useAttachments(guideId: string | null) {
  return useQuery({
    queryKey: [...GUIDES_QUERY_KEY, "attachments", guideId],
    queryFn: () => fetchAttachments(guideId as string),
    enabled: guideId !== null,
  });
}

export function useUploadAttachment() {
  return useGuidesMutation(uploadAttachment);
}

export function useDeleteAttachment() {
  return useGuidesMutation(deleteAttachment);
}

export function useCreateGuide() {
  return useGuidesMutation(postGuide);
}

export function useUpdateGuide() {
  return useGuidesMutation(patchGuide);
}

export function useDeleteGuide() {
  return useGuidesMutation(deleteGuide);
}
