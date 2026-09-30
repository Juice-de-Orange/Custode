import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { FeedbackCreate, FeedbackResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

export const FEEDBACK_QUERY_KEY = ["feedback"] as const;

async function fetchFeedback(): Promise<FeedbackResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/feedback" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as FeedbackResponse[];
}

async function postFeedback(body: FeedbackCreate): Promise<FeedbackResponse> {
  const { data, error, response } = await client.post({ url: "/v1/feedback", body });
  if (error) throw toProblem(error, response?.status);
  return data as FeedbackResponse;
}

export function useFeedback() {
  return useQuery({ queryKey: FEEDBACK_QUERY_KEY, queryFn: fetchFeedback });
}

export function useSubmitFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postFeedback,
    onSuccess: () => qc.invalidateQueries({ queryKey: FEEDBACK_QUERY_KEY }),
  });
}
