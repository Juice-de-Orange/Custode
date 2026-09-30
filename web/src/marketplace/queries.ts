import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  AutoAcceptRuleCreate,
  AutoAcceptRuleResponse,
  ListingCreate,
  ListingResponse,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

async function fetchListings(): Promise<ListingResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/marketplace/listings" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as ListingResponse[];
}

async function postListing(body: ListingCreate): Promise<ListingResponse> {
  const { data, error, response } = await client.post({ url: "/v1/marketplace/listings", body });
  if (error) throw toProblem(error, response?.status);
  return data as ListingResponse;
}

function listingAction(action: "accept" | "withdraw" | "settle") {
  return async (id: string): Promise<void> => {
    const { error, response } = await client.post({
      url: `/v1/marketplace/listings/${id}/${action}`,
    });
    if (error) throw toProblem(error, response?.status);
  };
}

export const LISTINGS_QUERY_KEY = ["marketplace", "listings"] as const;

export function useListings() {
  return useQuery({ queryKey: LISTINGS_QUERY_KEY, queryFn: fetchListings });
}

// A marketplace action moves escrow + reassigns tasks, so refresh listings, balance + tasks.
function useMarketplaceMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LISTINGS_QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["economy"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useCreateListing() {
  return useMarketplaceMutation(postListing);
}

export function useAcceptListing() {
  return useMarketplaceMutation(listingAction("accept"));
}

export function useWithdrawListing() {
  return useMarketplaceMutation(listingAction("withdraw"));
}

export function useSettleListing() {
  return useMarketplaceMutation(listingAction("settle"));
}

// --- Auto-accept rules -------------------------------------------------------

async function fetchRules(): Promise<AutoAcceptRuleResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/marketplace/auto-accept" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as AutoAcceptRuleResponse[];
}

async function postRule(body: AutoAcceptRuleCreate): Promise<AutoAcceptRuleResponse> {
  const { data, error, response } = await client.post({ url: "/v1/marketplace/auto-accept", body });
  if (error) throw toProblem(error, response?.status);
  return data as AutoAcceptRuleResponse;
}

async function deleteRule(id: string): Promise<void> {
  const { error, response } = await client.delete({
    url: `/v1/marketplace/auto-accept/${id}`,
  });
  if (error) throw toProblem(error, response?.status);
}

export const RULES_QUERY_KEY = ["marketplace", "auto-accept"] as const;

export function useAutoAcceptRules() {
  return useQuery({ queryKey: RULES_QUERY_KEY, queryFn: fetchRules });
}

// Creating a rule can immediately auto-accept an open listing, so refresh listings too.
function useRulesMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_QUERY_KEY });
      qc.invalidateQueries({ queryKey: LISTINGS_QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["economy"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useCreateRule() {
  return useRulesMutation(postRule);
}

export function useDeleteRule() {
  return useRulesMutation(deleteRule);
}
