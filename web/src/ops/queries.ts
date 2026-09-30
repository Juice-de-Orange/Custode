import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  AuditLogEntry,
  BannerCreate,
  BannerResponse,
  HouseholdMetadata,
  OperatorLogin,
  OperatorMe,
  OperatorPasskeySummary,
  OperatorSession,
  OperatorSummary,
  OpsFeedbackEntry,
  OpsFlags,
  OpsHealth,
  OpsKpis,
} from "../api/types.gen";
import {
  assertionToJson,
  attestationToJson,
  optionsToCreate,
  optionsToGet,
  type ServerAssertionOptions,
  type ServerCreationOptions,
} from "../auth/webauthn";
import { ProblemError, toProblem } from "../lib/problem";
import { hasOpsToken, opsClient, setOpsToken } from "./client";

export const OPS_ME_QUERY_KEY = ["ops", "me"] as const;

// The authenticated operator, or null when not signed in. A 401 is "not authenticated"
// (the bearer interceptor already dropped the token); other errors surface as ErrorState.
async function fetchOpsMe(): Promise<OperatorMe | null> {
  if (!hasOpsToken()) return null;
  const { data, error, response } = await opsClient.get({ url: "/ops/me" });
  if (error) {
    if (response?.status === 401) return null;
    throw toProblem(error, response?.status);
  }
  return data as OperatorMe;
}

async function postOpsLogin(body: OperatorLogin): Promise<OperatorSession> {
  const { data, error, response } = await opsClient.post({ url: "/ops/auth/login", body });
  if (error) throw toProblem(error, response?.status);
  return data as OperatorSession;
}

async function postOpsLogout(): Promise<void> {
  // Best-effort revoke; the local token is cleared regardless so the device is logged out.
  try {
    await opsClient.post({ url: "/ops/auth/logout" });
  } catch {
    /* ignore */
  }
}

export function useOpsSession() {
  return useQuery({ queryKey: OPS_ME_QUERY_KEY, queryFn: fetchOpsMe, staleTime: 0 });
}

export function useOpsLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postOpsLogin,
    onSuccess: (session) => {
      setOpsToken(session.token);
      qc.invalidateQueries({ queryKey: OPS_ME_QUERY_KEY });
    },
  });
}

export function useOpsLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postOpsLogout,
    onSuccess: () => {
      setOpsToken(null);
      qc.setQueryData(OPS_ME_QUERY_KEY, null);
    },
  });
}

// ----------------------------------------------------------------- dashboard (S-OPS-FE-b)

export const OPS_KPIS_QUERY_KEY = ["ops", "kpis"] as const;
export const OPS_HEALTH_QUERY_KEY = ["ops", "health"] as const;

// Both read aggregate views / build info only — never a fact table (ADR-0015/0071).
async function fetchOpsKpis(): Promise<OpsKpis> {
  const { data, error, response } = await opsClient.get({ url: "/ops/kpis" });
  if (error) throw toProblem(error, response?.status);
  return data as OpsKpis;
}

async function fetchOpsHealth(): Promise<OpsHealth> {
  const { data, error, response } = await opsClient.get({ url: "/ops/health" });
  if (error) throw toProblem(error, response?.status);
  return data as OpsHealth;
}

export function useOpsKpis() {
  return useQuery({ queryKey: OPS_KPIS_QUERY_KEY, queryFn: fetchOpsKpis });
}

export function useOpsHealth() {
  return useQuery({ queryKey: OPS_HEALTH_QUERY_KEY, queryFn: fetchOpsHealth });
}

// ----------------------------------------------------------- banners + flags (S-OPS-FE-c)
// Both write paths are audited server-side (record_audit) and run as ops_actions.

export const OPS_BANNERS_QUERY_KEY = ["ops", "banners"] as const;
export const OPS_FLAGS_QUERY_KEY = ["ops", "flags"] as const;

async function fetchBanners(): Promise<BannerResponse[]> {
  const { data, error, response } = await opsClient.get({ url: "/ops/banners" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as BannerResponse[];
}

async function postBanner(body: BannerCreate): Promise<BannerResponse> {
  const { data, error, response } = await opsClient.post({ url: "/ops/banners", body });
  if (error) throw toProblem(error, response?.status);
  return data as BannerResponse;
}

async function deactivateBanner(id: string): Promise<BannerResponse> {
  const { data, error, response } = await opsClient.post({
    url: `/ops/banners/${id}/deactivate`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as BannerResponse;
}

async function fetchFlags(): Promise<OpsFlags> {
  const { data, error, response } = await opsClient.get({ url: "/ops/flags" });
  if (error) throw toProblem(error, response?.status);
  return data as OpsFlags;
}

async function putFlag(vars: { key: string; enabled: boolean }): Promise<OpsFlags> {
  const { data, error, response } = await opsClient.put({
    url: `/ops/flags/${vars.key}`,
    body: { enabled: vars.enabled },
  });
  if (error) throw toProblem(error, response?.status);
  return data as OpsFlags;
}

export function useOpsBanners() {
  return useQuery({ queryKey: OPS_BANNERS_QUERY_KEY, queryFn: fetchBanners });
}

export function useCreateBanner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postBanner,
    onSuccess: () => qc.invalidateQueries({ queryKey: OPS_BANNERS_QUERY_KEY }),
  });
}

export function useDeactivateBanner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deactivateBanner,
    onSuccess: () => qc.invalidateQueries({ queryKey: OPS_BANNERS_QUERY_KEY }),
  });
}

export function useOpsFlags() {
  return useQuery({ queryKey: OPS_FLAGS_QUERY_KEY, queryFn: fetchFlags });
}

export function useSetFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: putFlag,
    // The endpoint returns the full flag state, so seed the cache directly.
    onSuccess: (flags) => qc.setQueryData(OPS_FLAGS_QUERY_KEY, flags),
  });
}

// ------------------------------------------------- support search + feedback (S-OPS-FE-d)
// Both read aggregate views (household_metadata / ops_feedback), never a fact table — support
// search is metadata-only (no recipes/tasks/messages), ADR-0015.

export const OPS_HOUSEHOLDS_QUERY_KEY = ["ops", "households"] as const;
export const OPS_FEEDBACK_QUERY_KEY = ["ops", "feedback"] as const;

async function searchHouseholds(q: string): Promise<HouseholdMetadata[]> {
  const { data, error, response } = await opsClient.get({
    url: "/ops/households",
    query: { q },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as HouseholdMetadata[];
}

async function fetchOpsFeedback(category: string | null): Promise<OpsFeedbackEntry[]> {
  const { data, error, response } = await opsClient.get({
    url: "/ops/feedback",
    query: category ? { category } : undefined,
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as OpsFeedbackEntry[];
}

export function useSearchHouseholds(q: string) {
  return useQuery({
    queryKey: [...OPS_HOUSEHOLDS_QUERY_KEY, q] as const,
    queryFn: () => searchHouseholds(q),
  });
}

export function useOpsFeedback(category: string | null) {
  return useQuery({
    queryKey: [...OPS_FEEDBACK_QUERY_KEY, category ?? ""] as const,
    queryFn: () => fetchOpsFeedback(category),
  });
}

// ---------------------------------------------------- operator management (S-OPS-FE-e)
// List + activate/deactivate operators; the write paths are audited server-side (record_audit,
// ops_actions). Provisioning stays CLI/seed (ADR-0015) — this UI manages activation, not credentials.

export const OPS_OPERATORS_QUERY_KEY = ["ops", "operators"] as const;

async function fetchOperators(): Promise<OperatorSummary[]> {
  const { data, error, response } = await opsClient.get({ url: "/ops/operators" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as OperatorSummary[];
}

async function setOperatorActive(vars: { id: string; active: boolean }): Promise<OperatorSummary> {
  const { data, error, response } = await opsClient.post({
    url: `/ops/operators/${vars.id}/${vars.active ? "reactivate" : "deactivate"}`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as OperatorSummary;
}

export function useOpsOperators() {
  return useQuery({ queryKey: OPS_OPERATORS_QUERY_KEY, queryFn: fetchOperators });
}

export function useSetOperatorActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: setOperatorActive,
    onSuccess: () => qc.invalidateQueries({ queryKey: OPS_OPERATORS_QUERY_KEY }),
  });
}

// ------------------------------------------------------- operator passkeys (ADR-0072, S-OPS-FE-f)
// Reuses the pure browser ceremony helpers (../auth/webauthn); the ops flow is COOKIELESS — the
// passwordless-login flow_id is returned in the body and echoed back on complete (never a cookie).

export const OPS_PASSKEYS_QUERY_KEY = ["ops", "passkeys"] as const;

async function fetchOpsPasskeys(): Promise<OperatorPasskeySummary[]> {
  const { data, error, response } = await opsClient.get({ url: "/ops/passkeys" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as OperatorPasskeySummary[];
}

async function registerOpsPasskey(name: string): Promise<void> {
  const begin = await opsClient.post({ url: "/ops/auth/passkeys/register/begin" });
  if (begin.error) throw toProblem(begin.error, begin.response?.status);
  const { options } = begin.data as { options: ServerCreationOptions };
  const credential = await navigator.credentials.create({ publicKey: optionsToCreate(options) });
  if (!(credential instanceof PublicKeyCredential)) throw new ProblemError("passkey_cancelled");
  const complete = await opsClient.post({
    url: "/ops/auth/passkeys/register/complete",
    body: { credential: attestationToJson(credential), name },
  });
  if (complete.error) throw toProblem(complete.error, complete.response?.status);
}

async function deleteOpsPasskey(id: string): Promise<void> {
  const { error, response } = await opsClient.delete({ url: `/ops/passkeys/${id}` });
  if (error) throw toProblem(error, response?.status);
}

// Passwordless operator login: the challenge is bound by an opaque flow_id we echo back (no cookie).
async function opsPasskeyLogin(): Promise<OperatorSession> {
  const begin = await opsClient.post({ url: "/ops/auth/passkeys/login/begin" });
  if (begin.error) throw toProblem(begin.error, begin.response?.status);
  const { options, flow_id } = begin.data as { options: ServerAssertionOptions; flow_id: string };
  const credential = await navigator.credentials.get({ publicKey: optionsToGet(options) });
  if (!(credential instanceof PublicKeyCredential)) throw new ProblemError("passkey_cancelled");
  const complete = await opsClient.post({
    url: "/ops/auth/passkeys/login/complete",
    body: { credential: assertionToJson(credential), flow_id },
  });
  if (complete.error) throw toProblem(complete.error, complete.response?.status);
  return complete.data as OperatorSession;
}

export function useOpsPasskeys() {
  return useQuery({ queryKey: OPS_PASSKEYS_QUERY_KEY, queryFn: fetchOpsPasskeys });
}

export function useRegisterOpsPasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: registerOpsPasskey,
    onSuccess: () => qc.invalidateQueries({ queryKey: OPS_PASSKEYS_QUERY_KEY }),
  });
}

export function useDeleteOpsPasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteOpsPasskey,
    onSuccess: () => qc.invalidateQueries({ queryKey: OPS_PASSKEYS_QUERY_KEY }),
  });
}

export function useOpsPasskeyLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: opsPasskeyLogin,
    onSuccess: (session) => {
      setOpsToken(session.token);
      qc.invalidateQueries({ queryKey: OPS_ME_QUERY_KEY });
    },
  });
}

// ------------------------------------------------------------ audit trail (S-OPS-FE-g)
// Read-only view of the append-only audit_log (ops_readonly SELECT). The trail is PII-free by
// construction, so reading it is not itself audited. Filtering by action is done client-side.

export const OPS_AUDIT_QUERY_KEY = ["ops", "audit"] as const;

async function fetchOpsAudit(): Promise<AuditLogEntry[]> {
  const { data, error, response } = await opsClient.get({
    url: "/ops/audit",
    query: { limit: 200 },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as AuditLogEntry[];
}

export function useOpsAudit() {
  return useQuery({ queryKey: OPS_AUDIT_QUERY_KEY, queryFn: fetchOpsAudit });
}
