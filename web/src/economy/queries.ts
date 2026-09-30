import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  BalanceResponse,
  ChallengeResponse,
  FairnessResponse,
  LedgerEntryResponse,
  MemberResponse,
  RedemptionResponse,
  RewardCreate,
  RewardResponse,
  ThanksRequest,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

async function fetchBalance(): Promise<BalanceResponse> {
  const { data, error, response } = await client.get({ url: "/v1/economy/balance" });
  if (error) throw toProblem(error, response?.status);
  return data as BalanceResponse;
}

async function fetchLedger(): Promise<LedgerEntryResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/economy/ledger" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as LedgerEntryResponse[];
}

export const BALANCE_QUERY_KEY = ["economy", "balance"] as const;
export const LEDGER_QUERY_KEY = ["economy", "ledger"] as const;

export function useBalance() {
  return useQuery({ queryKey: BALANCE_QUERY_KEY, queryFn: fetchBalance });
}

export function useLedger() {
  return useQuery({ queryKey: LEDGER_QUERY_KEY, queryFn: fetchLedger });
}

// --- Rewards + redemptions ---------------------------------------------------

async function fetchRewards(): Promise<RewardResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/economy/rewards" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as RewardResponse[];
}

async function fetchRedemptions(): Promise<RedemptionResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/economy/redemptions" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as RedemptionResponse[];
}

async function postReward(body: RewardCreate): Promise<RewardResponse> {
  const { data, error, response } = await client.post({ url: "/v1/economy/rewards", body });
  if (error) throw toProblem(error, response?.status);
  return data as RewardResponse;
}

async function deleteReward(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/economy/rewards/${id}` });
  if (error) throw toProblem(error, response?.status);
}

async function redeemReward(id: string): Promise<RedemptionResponse> {
  const { data, error, response } = await client.post({
    url: `/v1/economy/rewards/${id}/redeem`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as RedemptionResponse;
}

async function fulfillRedemption(id: string): Promise<RedemptionResponse> {
  const { data, error, response } = await client.post({
    url: `/v1/economy/redemptions/${id}/fulfill`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as RedemptionResponse;
}

export const REWARDS_QUERY_KEY = ["economy", "rewards"] as const;
export const REDEMPTIONS_QUERY_KEY = ["economy", "redemptions"] as const;

export function useRewards() {
  return useQuery({ queryKey: REWARDS_QUERY_KEY, queryFn: fetchRewards });
}

export function useRedemptions() {
  return useQuery({ queryKey: REDEMPTIONS_QUERY_KEY, queryFn: fetchRedemptions });
}

// Any economy mutation can move the balance and the lists — invalidate the whole economy subtree.
function useEconomyMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["economy"] }),
  });
}

export function useCreateReward() {
  return useEconomyMutation(postReward);
}

export function useDeleteReward() {
  return useEconomyMutation(deleteReward);
}

export function useRedeemReward() {
  return useEconomyMutation(redeemReward);
}

export function useFulfillRedemption() {
  return useEconomyMutation(fulfillRedemption);
}

// --- Thanks + weekly challenge -----------------------------------------------

async function fetchChallenge(): Promise<ChallengeResponse> {
  const { data, error, response } = await client.get({ url: "/v1/economy/challenge" });
  if (error) throw toProblem(error, response?.status);
  return data as ChallengeResponse;
}

async function fetchMembers(): Promise<MemberResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/household/members" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as MemberResponse[];
}

async function postThanks(body: ThanksRequest): Promise<void> {
  const { error, response } = await client.post({ url: "/v1/economy/thanks", body });
  if (error) throw toProblem(error, response?.status);
}

async function fetchFairness(): Promise<FairnessResponse> {
  const { data, error, response } = await client.get({ url: "/v1/economy/fairness" });
  if (error) throw toProblem(error, response?.status);
  return data as FairnessResponse;
}

export const CHALLENGE_QUERY_KEY = ["economy", "challenge"] as const;
export const FAIRNESS_QUERY_KEY = ["economy", "fairness"] as const;
export const MEMBERS_QUERY_KEY = ["household", "members"] as const;

export function useChallenge() {
  return useQuery({ queryKey: CHALLENGE_QUERY_KEY, queryFn: fetchChallenge });
}

export function useFairness() {
  return useQuery({ queryKey: FAIRNESS_QUERY_KEY, queryFn: fetchFairness });
}

export function useHouseholdMembers() {
  return useQuery({ queryKey: MEMBERS_QUERY_KEY, queryFn: fetchMembers });
}

export function useSendThanks() {
  return useEconomyMutation(postThanks);
}
