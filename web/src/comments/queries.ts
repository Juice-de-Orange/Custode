import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { CommentResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

export const COMMENTS_QUERY_KEY = ["comments"] as const;

async function fetchThread(objectType: string, objectId: string): Promise<CommentResponse[]> {
  const { data, error, response } = await client.get({
    url: "/v1/comments",
    query: { object_type: objectType, object_id: objectId },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as CommentResponse[];
}

async function postComment(vars: {
  objectType: string;
  objectId: string;
  bodyMd: string;
}): Promise<CommentResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/comments",
    body: { object_type: vars.objectType, object_id: vars.objectId, body_md: vars.bodyMd },
  });
  if (error) throw toProblem(error, response?.status);
  return data as CommentResponse;
}

async function patchComment(vars: {
  id: string;
  bodyMd: string;
  version: number;
}): Promise<CommentResponse> {
  // The thread carries each comment's version, so If-Match needs no extra GET (ADR-0029); 412 = stale.
  const { data, error, response } = await client.patch({
    url: `/v1/comments/${vars.id}`,
    body: { body_md: vars.bodyMd },
    headers: { "If-Match": `"${vars.version}"` },
  });
  if (error) throw toProblem(error, response?.status);
  return data as CommentResponse;
}

async function deleteComment(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/comments/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export function useThread(objectType: string, objectId: string | null) {
  return useQuery({
    queryKey: [...COMMENTS_QUERY_KEY, objectType, objectId],
    queryFn: () => fetchThread(objectType, objectId as string),
    enabled: objectId !== null,
  });
}

export function usePostComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postComment,
    onSuccess: () => qc.invalidateQueries({ queryKey: COMMENTS_QUERY_KEY }),
  });
}

export function useEditComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchComment,
    onSuccess: () => qc.invalidateQueries({ queryKey: COMMENTS_QUERY_KEY }),
  });
}

export function useDeleteComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteComment,
    onSuccess: () => qc.invalidateQueries({ queryKey: COMMENTS_QUERY_KEY }),
  });
}
