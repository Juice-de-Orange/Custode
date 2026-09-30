// Account deletion (Art. 17, 11-S1c). Two routes: ask what stands in the way, then ask for it.
//
// The blockers are fetched **lazily** — only once the person opens the danger zone. They are not
// needed to render /profile, and asking on every visit would put a cross-household query behind a
// page that most people open to change their display name.
//
// Deliberately no optimistic anything: the request revokes every session server-side, so the very
// next call would 401. The caller navigates to /login on success.

import { useMutation, useQuery } from "@tanstack/react-query";

import type { DeletionBlockerResponse } from "../api/types.gen";
import { client } from "../api/client.gen";
import { toProblem } from "../lib/problem";

export const DELETION_BLOCKERS_QUERY_KEY = ["account", "deletion-blockers"] as const;

async function getBlockers(): Promise<DeletionBlockerResponse[]> {
  const { data, error, response } = await client.get({
    url: "/v1/auth/account/deletion-blockers",
  });
  if (error) throw toProblem(error, response?.status);
  return data as DeletionBlockerResponse[];
}

async function deleteAccount(): Promise<void> {
  const { error, response } = await client.delete({ url: "/v1/auth/account" });
  if (error) throw toProblem(error, response?.status);
}

/** ``enabled`` so the danger zone can stay closed without costing a request. ``staleTime: 0``
 *  because a role change in another tab is exactly the thing that flips the answer. */
export function useDeletionBlockers(enabled: boolean) {
  return useQuery({
    queryKey: DELETION_BLOCKERS_QUERY_KEY,
    queryFn: getBlockers,
    enabled,
    staleTime: 0,
  });
}

/** No retry. A request that already went through and then looked like a network failure must not
 *  be repeated — the second call would 401 and read as an error on an account that is gone. */
export function useDeleteAccount() {
  return useMutation({ mutationFn: deleteAccount, retry: false });
}
