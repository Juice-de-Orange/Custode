import { useQuery } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { BannerResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

export const BANNERS_QUERY_KEY = ["banners"] as const;

async function fetchActiveBanners(): Promise<BannerResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/banners" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as BannerResponse[];
}

// Active global operator banners (maintenance notices). Only fetched while signed in (the endpoint
// requires a session). Operator-authored content — displayed as-is, no i18n.
export function useActiveBanners(enabled: boolean) {
  return useQuery({ queryKey: BANNERS_QUERY_KEY, queryFn: fetchActiveBanners, enabled });
}
