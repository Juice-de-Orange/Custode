import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  LetterCreate,
  LetterResponse,
  LetterSummary,
  LetterToTaskResult,
  UnreadCount,
} from "../api/types.gen";
import { toProblem } from "../auth/session";
import { TASKS_QUERY_KEY } from "../tasks/queries";

export const LETTERS_QUERY_KEY = ["letters"] as const;

async function fetchInbox(): Promise<LetterSummary[]> {
  const { data, error, response } = await client.get({ url: "/v1/letters" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as LetterSummary[];
}

async function fetchUnread(): Promise<UnreadCount> {
  const { data, error, response } = await client.get({ url: "/v1/letters/unread-count" });
  if (error) throw toProblem(error, response?.status);
  return data as UnreadCount;
}

async function fetchLetter(id: string): Promise<LetterResponse> {
  const { data, error, response } = await client.get({ url: `/v1/letters/${id}` });
  if (error) throw toProblem(error, response?.status);
  return data as LetterResponse;
}

async function postLetter(body: LetterCreate): Promise<LetterResponse> {
  const { data, error, response } = await client.post({ url: "/v1/letters", body });
  if (error) throw toProblem(error, response?.status);
  return data as LetterResponse;
}

export function useInbox() {
  return useQuery({ queryKey: LETTERS_QUERY_KEY, queryFn: fetchInbox });
}

export function useUnreadCount() {
  return useQuery({ queryKey: [...LETTERS_QUERY_KEY, "unread"], queryFn: fetchUnread });
}

export function useLetter(id: string | null) {
  return useQuery({
    queryKey: [...LETTERS_QUERY_KEY, id],
    queryFn: () => fetchLetter(id as string),
    enabled: id !== null,
  });
}

export function useSendLetter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postLetter,
    onSuccess: () => qc.invalidateQueries({ queryKey: LETTERS_QUERY_KEY }),
  });
}

async function convertToTask(id: string): Promise<LetterToTaskResult> {
  const { data, error, response } = await client.post({ url: `/v1/letters/${id}/to-task` });
  if (error) throw toProblem(error, response?.status);
  return data as LetterToTaskResult;
}

export function useConvertToTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: convertToTask,
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}
