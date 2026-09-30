// Household membership management (KONZEPT §5.1). Four routes, three of which the backend has
// carried since Phase 1 without a single caller in the web — the list, the role change and the
// removal. That was not a cosmetic gap: ``request_account_deletion`` answers 409 ``last_admin``
// with the sentence "übertrage zuerst die Admin-Rolle an ein anderes Mitglied", and until this
// slice there was no surface anywhere that could carry out that instruction. A documented way out
// that cannot be walked is a dead end wearing a sign.
//
// The fourth, ``POST /v1/household/leave``, is new: leaving was only ever something an admin did
// *to* someone. KONZEPT §5.1 frames it as the person's own right.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { DissolvePreview, MemberResponse, Role } from "../api/types.gen";
import { client } from "../api/client.gen";
import { HOUSEHOLDS_QUERY_KEY, ME_QUERY_KEY } from "../auth/session";
import { toProblem } from "../lib/problem";

export const MEMBERS_QUERY_KEY = ["household", "members"] as const;

async function getMembers(): Promise<MemberResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/household/members" });
  if (error) throw toProblem(error, response?.status);
  return data as MemberResponse[];
}

async function patchMemberRole(vars: { membershipId: string; role: Role }): Promise<void> {
  const { error, response } = await client.patch({
    url: `/v1/household/members/${vars.membershipId}`,
    body: { role: vars.role },
  });
  if (error) throw toProblem(error, response?.status);
}

async function deleteMember(membershipId: string): Promise<void> {
  const { error, response } = await client.delete({
    url: `/v1/household/members/${membershipId}`,
  });
  if (error) throw toProblem(error, response?.status);
}

async function postLeave(): Promise<void> {
  const { error, response } = await client.post({ url: "/v1/household/leave" });
  if (error) throw toProblem(error, response?.status);
}

export function useMembers(enabled = true) {
  return useQuery({ queryKey: MEMBERS_QUERY_KEY, queryFn: getMembers, enabled });
}

/** A role change alters what the *calling* admin may do next — demoting yourself is legal as long
 *  as somebody else is admin — so ``/me`` is invalidated alongside the roster. */
export function useChangeMemberRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchMemberRole,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MEMBERS_QUERY_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useRemoveMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteMember,
    onSuccess: () => qc.invalidateQueries({ queryKey: MEMBERS_QUERY_KEY }),
  });
}

/** Leaving revokes **every** session of the caller server-side, including this one. The cache is
 *  therefore cleared rather than invalidated: refetching with dead cookies would only produce a
 *  wave of 401s on the way out. The caller navigates to /login. */
export function useLeaveHousehold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postLeave,
    onSuccess: () => {
      qc.removeQueries({ queryKey: MEMBERS_QUERY_KEY });
      qc.removeQueries({ queryKey: HOUSEHOLDS_QUERY_KEY });
      qc.removeQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}


// --- Auflösung (Art. 17, ADR-0085) --------------------------------------------------------------
// Die Vorschau wird **lazy** geholt, erst wenn die Gefahrenzone geöffnet wird — wie bei der
// Kontolöschung. `/account` ist die Landeseite jeder Sitzung; eine Abfrage, die nur ein Admin
// jemals braucht, gehört dort nicht in den Erstaufbau.

export const DISSOLVE_PREVIEW_QUERY_KEY = ["household", "dissolve-preview"] as const;

async function getDissolvePreview(): Promise<DissolvePreview> {
  const { data, error, response } = await client.get({ url: "/v1/household/dissolve-preview" });
  if (error) throw toProblem(error, response?.status);
  return data as DissolvePreview;
}

async function postDissolve(confirmName: string): Promise<void> {
  const { error, response } = await client.post({
    url: "/v1/household/dissolve",
    body: { confirm_name: confirmName },
  });
  if (error) throw toProblem(error, response?.status);
}

export function useDissolvePreview(enabled: boolean) {
  return useQuery({
    queryKey: DISSOLVE_PREVIEW_QUERY_KEY,
    queryFn: getDissolvePreview,
    enabled,
    staleTime: 0,
  });
}

/** No retry: the request ends every session in the household, so a second attempt would 401 and
 *  read as a failure on a household that is already gone. */
export function useDissolveHousehold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postDissolve,
    retry: false,
    onSuccess: () => qc.clear(),
  });
}
