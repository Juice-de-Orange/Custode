// Wearable connection hooks (P9-S8). Health data is member-private: this is the only place the
// web touches it, and every response carries has_tokens at most — never a token, never a raw
// score (the backend seam hands other modules a boolean, not a value; ADR-0081).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ConnectionResponse } from "../api/types.gen";
import { client } from "../api/client.gen";
import { toProblem } from "../lib/problem";

export const WEARABLES_QUERY_KEY = ["wearables"] as const;
const CONNECTIONS_KEY = [...WEARABLES_QUERY_KEY, "connections"] as const;

/** The consentable data types, in the order the backend returns them (types.py). */
export const CONSENT_TYPES = [
  "wearable_sleep",
  "wearable_readiness",
  "wearable_activity",
  "wearable_heartrate",
] as const;

export type ConsentType = (typeof CONSENT_TYPES)[number];

async function fetchConnections(): Promise<ConnectionResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/wearables/connections" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as ConnectionResponse[];
}

async function postAuthorize(consentTypes: string[]): Promise<string> {
  const { data, error, response } = await client.post({
    url: "/v1/wearables/oura/authorize",
    body: { consent_types: consentTypes },
  });
  if (error) throw toProblem(error, response?.status);
  return (data as { authorize_url: string }).authorize_url;
}

async function patchConsents(vars: {
  id: string;
  consentTypes: string[];
}): Promise<ConnectionResponse | null> {
  const { data, error, response } = await client.patch({
    url: `/v1/wearables/connections/${vars.id}/consents`,
    body: { consent_types: vars.consentTypes },
  });
  if (error) throw toProblem(error, response?.status);
  // Withdrawing the last type disconnects entirely and answers null (Art. 9: a connection
  // without consent must not survive) — the caller renders the empty state, not a stale card.
  return (data ?? null) as ConnectionResponse | null;
}

async function deleteConnection(id: string): Promise<void> {
  const { error, response } = await client.delete({
    url: `/v1/wearables/connections/${id}`,
  });
  if (error) throw toProblem(error, response?.status);
}

export function useConnections() {
  return useQuery({ queryKey: CONNECTIONS_KEY, queryFn: fetchConnections });
}

/** Starts the OAuth flow. On success the browser LEAVES for the provider — deliberately a
 *  full navigation, not a popup: the callback is a server-side redirect back into the app. */
export function useAuthorize() {
  return useMutation({ mutationFn: postAuthorize });
}

export function useUpdateConsents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchConsents,
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTIONS_KEY }),
  });
}

export function useDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteConnection,
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTIONS_KEY }),
  });
}
