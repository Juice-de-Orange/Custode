import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { DigestSetting } from "../api/types.gen";
import { toProblem } from "../auth/session";

export const DIGEST_SETTING_QUERY_KEY = ["household", "digest"] as const;

async function fetchDigest(): Promise<DigestSetting> {
  const { data, error, response } = await client.get({ url: "/v1/household/digest" });
  if (error) throw toProblem(error, response?.status);
  return data as DigestSetting;
}

async function patchDigest(enabled: boolean): Promise<DigestSetting> {
  const { data, error, response } = await client.patch({
    url: "/v1/household/digest",
    body: { enabled },
  });
  if (error) throw toProblem(error, response?.status);
  return data as DigestSetting;
}

// Weekly-digest opt-out for the active household (admin only, P8-S7b). Enabled only when the caller
// is an admin (the endpoint is admin-guarded).
export function useDigestSetting(enabled: boolean) {
  return useQuery({ queryKey: DIGEST_SETTING_QUERY_KEY, queryFn: fetchDigest, enabled });
}

export function useSetDigestSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchDigest,
    onSuccess: () => qc.invalidateQueries({ queryKey: DIGEST_SETTING_QUERY_KEY }),
  });
}
