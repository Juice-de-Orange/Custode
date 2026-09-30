import { useMutation } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { SlotResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

export type SlotQuery = {
  from: string;
  to: string;
  durationMin: number;
  limit?: number;
};

async function fetchSlots(q: SlotQuery): Promise<SlotResponse[]> {
  const { data, error, response } = await client.get({
    url: "/v1/scheduling/slots",
    query: { from: q.from, to: q.to, duration_min: q.durationMin, limit: q.limit ?? 5 },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as SlotResponse[];
}

// On-demand (the user clicks "find slots"), so a mutation rather than a standing query.
export function useSuggestSlots() {
  return useMutation({ mutationFn: fetchSlots });
}
