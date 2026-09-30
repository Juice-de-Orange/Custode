import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { CaptureCreate, CaptureResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

async function fetchInbox(): Promise<CaptureResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/capture/inbox" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as CaptureResponse[];
}

async function postCapture(body: CaptureCreate): Promise<CaptureResponse> {
  const { data, error, response } = await client.post({ url: "/v1/capture", body });
  if (error) throw toProblem(error, response?.status);
  return data as CaptureResponse;
}

function captureAction(action: "confirm" | "dismiss") {
  return async (id: string): Promise<void> => {
    const { error, response } = await client.post({ url: `/v1/capture/${id}/${action}` });
    if (error) throw toProblem(error, response?.status);
  };
}

export const CAPTURE_QUERY_KEY = ["capture"] as const;

export function useInbox() {
  return useQuery({ queryKey: CAPTURE_QUERY_KEY, queryFn: fetchInbox });
}

// A capture action can create a shopping item / task, so refresh the inbox, shopping + tasks.
function useCaptureMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CAPTURE_QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["shopping"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function usePostCapture() {
  return useCaptureMutation(postCapture);
}

export function useConfirmCapture() {
  return useCaptureMutation(captureAction("confirm"));
}

export function useDismissCapture() {
  return useCaptureMutation(captureAction("dismiss"));
}
