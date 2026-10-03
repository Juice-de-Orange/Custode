import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  EnvelopeResponse,
  EnvelopeUpsert,
  VaultItemCreate,
  VaultItemResponse,
  VaultItemSummary,
  VaultItemUpdate,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

export const VAULT_QUERY_KEY = ["vault"] as const;

// A vault item plus its ETag (row version) so a PATCH can send If-Match (ADR-0029); 412 = stale.
export type VaultItemWithEtag = VaultItemResponse & { etag: string };

function withEtag(data: unknown, response: Response | undefined): VaultItemWithEtag {
  return { ...(data as VaultItemResponse), etag: response?.headers.get("etag") ?? "" };
}

async function fetchKeys(): Promise<EnvelopeResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/vault/keys" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as EnvelopeResponse[];
}

async function putKey(body: EnvelopeUpsert): Promise<EnvelopeResponse> {
  const { data, error, response } = await client.put({ url: "/v1/vault/keys", body });
  if (error) throw toProblem(error, response?.status);
  return data as EnvelopeResponse;
}

async function fetchItems(): Promise<VaultItemSummary[]> {
  const { data, error, response } = await client.get({ url: "/v1/vault/items" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as VaultItemSummary[];
}

async function fetchItem(id: string): Promise<VaultItemWithEtag> {
  const { data, error, response } = await client.get({ url: `/v1/vault/items/${id}` });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function postItem(body: VaultItemCreate): Promise<VaultItemWithEtag> {
  const { data, error, response } = await client.post({ url: "/v1/vault/items", body });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function patchItem(vars: {
  id: string;
  update: VaultItemUpdate;
  etag: string;
}): Promise<VaultItemWithEtag> {
  const { data, error, response } = await client.patch({
    url: `/v1/vault/items/${vars.id}`,
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function deleteItem(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/vault/items/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export function useVaultKeys(enabled = true) {
  return useQuery({ queryKey: [...VAULT_QUERY_KEY, "keys"], queryFn: fetchKeys, enabled });
}

export function usePutKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: putKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULT_QUERY_KEY }),
  });
}

export function useVaultItems() {
  return useQuery({ queryKey: [...VAULT_QUERY_KEY, "items"], queryFn: fetchItems });
}

export function useVaultItem(id: string | null) {
  return useQuery({
    queryKey: [...VAULT_QUERY_KEY, "items", id],
    queryFn: () => fetchItem(id as string),
    enabled: id !== null,
  });
}

function useVaultMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: VAULT_QUERY_KEY }),
  });
}

export function useCreateItem() {
  return useVaultMutation(postItem);
}

export function useUpdateItem() {
  return useVaultMutation(patchItem);
}

export function useDeleteItem() {
  return useVaultMutation(deleteItem);
}
