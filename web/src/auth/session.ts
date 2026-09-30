import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import { ProblemError, toProblem } from "../lib/problem";
import {
  assertionToJson,
  attestationToJson,
  optionsToCreate,
  optionsToGet,
  type ServerAssertionOptions,
  type ServerCreationOptions,
} from "./webauthn";

// Re-exported for existing call sites that import these from ``../auth/session``.
export { ProblemError, toProblem };
import type {
  ChildLoginRequest,
  ChildResponse,
  CreateChildRequest,
  CreateHouseholdRequest,
  HouseholdSummary,
  InviteResponse,
  JoinRequest,
  LoginEventResponse,
  LoginRequest,
  MeResponse,
  PasskeyResponse,
  ProfileResponse,
  ProfileUpdate,
  RecoveryCodesResponse,
  RegisterRequest,
  SessionResponse,
  SessionView,
  TotpSetupResponse,
} from "../api/types.gen";

export async function fetchMe(): Promise<MeResponse | null> {
  const { data, error, response } = await client.get({ url: "/v1/auth/me" });
  if (error) {
    if (response?.status === 401) return null; // not authenticated (after a silent refresh attempt)
    throw toProblem(error, response?.status); // transient/server error -> ErrorState, not a logout
  }
  // Any signed-in session re-enables shopping writes (blocked by the logout purge so an
  // in-flight pull cannot repopulate the cache, ADR-0078). Covers every login path.
  void import("../shopping/db").then((m) => m.unblockShoppingWrites());
  return data as MeResponse;
}

async function postLogin(body: LoginRequest): Promise<SessionResponse> {
  const { data, error, response } = await client.post({ url: "/v1/auth/login", body });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

async function postRegister(body: RegisterRequest): Promise<SessionResponse> {
  const { data, error, response } = await client.post({ url: "/v1/auth/register", body });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

async function postLogout(): Promise<void> {
  await client.post({ url: "/v1/auth/logout" });
}

export const ME_QUERY_KEY = ["auth", "me"] as const;

export function useSession() {
  return useQuery({ queryKey: ME_QUERY_KEY, queryFn: fetchMe, staleTime: 0 });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postLogin,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postRegister,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      // Flush the offline outbox while the session still exists — afterwards /v1 is a 401.
      // Push only (a pull would fetch rows the purge below deletes again) and give a slow
      // network 3 s, then let the logout win. Lazy import: keeps Dexie out of the eager shell.
      try {
        const { push } = await import("../shopping/sync");
        await Promise.race([
          push(),
          new Promise((_, reject) => setTimeout(() => reject(new Error("push timeout")), 3000)),
        ]);
      } catch {
        // Offline/slow/failed: logout wins; unpushed ops are dropped with the purge (ADR-0078).
      }
      await postLogout();
    },
    onSuccess: async () => {
      // Leave nothing behind on a shared device (ADR-0078): the purge blocks further shopping
      // writes (in-flight pull) and clears Dexie; in-memory server state goes via
      // removeQueries — NOT qc.clear(), which would also drop this in-flight mutation and
      // swallow callers' own onSuccess (e.g. the redirect to /login). The SW cache needs no
      // purge: it only ever holds the public app shell, never /v1 responses.
      try {
        const { purgeShoppingCache } = await import("../shopping/db");
        await purgeShoppingCache();
      } catch {
        console.error("logout: local cache purge failed"); // fail loud, no PII
      }
      qc.removeQueries();
      qc.setQueryData(ME_QUERY_KEY, null);
    },
  });
}

// Passwordless login (WebAuthn, ADR-0023): fetch assertion options, run the browser
// ceremony, post the credential. The flow cookie set by /begin rides along (same-origin).
async function passkeyLogin(): Promise<void> {
  const begin = await client.post({ url: "/v1/auth/passkeys/login/begin" });
  if (begin.error) throw toProblem(begin.error, begin.response?.status);
  const { options } = begin.data as { options: ServerAssertionOptions };
  const credential = await navigator.credentials.get({ publicKey: optionsToGet(options) });
  if (!(credential instanceof PublicKeyCredential)) throw new ProblemError("passkey_cancelled");
  const complete = await client.post({
    url: "/v1/auth/passkeys/login/complete",
    body: { credential: assertionToJson(credential) },
  });
  if (complete.error) throw toProblem(complete.error, complete.response?.status);
}

export function usePasskeyLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: passkeyLogin,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

// ------------------------------------------------------- TOTP / 2FA + passkey management (S8)

// Enrollment: setup returns the (pending) secret + otpauth URI for the QR; enable confirms with
// a code and returns the one-time recovery codes; disable/regenerate need an active 2FA. /me's
// totp_enabled + recovery_codes_remaining change, so those mutations invalidate ME_QUERY_KEY.
async function postTotpSetup(): Promise<TotpSetupResponse> {
  const { data, error, response } = await client.post({ url: "/v1/auth/totp/setup" });
  if (error) throw toProblem(error, response?.status);
  return data as TotpSetupResponse;
}

async function postTotpEnable(code: string): Promise<RecoveryCodesResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/auth/totp/enable",
    body: { code },
  });
  if (error) throw toProblem(error, response?.status);
  return data as RecoveryCodesResponse;
}

async function postTotpDisable(code: string): Promise<void> {
  const { error, response } = await client.post({ url: "/v1/auth/totp/disable", body: { code } });
  if (error) throw toProblem(error, response?.status);
}

async function postRegenerateRecoveryCodes(): Promise<RecoveryCodesResponse> {
  const { data, error, response } = await client.post({ url: "/v1/auth/totp/recovery-codes" });
  if (error) throw toProblem(error, response?.status);
  return data as RecoveryCodesResponse;
}

export function useTotpSetup() {
  return useMutation({ mutationFn: postTotpSetup });
}

export function useTotpEnable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postTotpEnable,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

export function useTotpDisable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postTotpDisable,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

export function useRegenerateRecoveryCodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postRegenerateRecoveryCodes,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

// Passkey management (logged-in): list, register (begin → browser create → complete), delete.
// The register ceremony mirrors passkeyLogin on the create side (webauthn.ts optionsToCreate).
async function getPasskeys(): Promise<PasskeyResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/auth/passkeys" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as PasskeyResponse[];
}

async function registerPasskey(name: string): Promise<void> {
  const begin = await client.post({ url: "/v1/auth/passkeys/register/begin" });
  if (begin.error) throw toProblem(begin.error, begin.response?.status);
  const { options } = begin.data as { options: ServerCreationOptions };
  const credential = await navigator.credentials.create({ publicKey: optionsToCreate(options) });
  if (!(credential instanceof PublicKeyCredential)) throw new ProblemError("passkey_cancelled");
  const complete = await client.post({
    url: "/v1/auth/passkeys/register/complete",
    body: { credential: attestationToJson(credential), name },
  });
  if (complete.error) throw toProblem(complete.error, complete.response?.status);
}

async function deletePasskey(passkeyId: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/auth/passkeys/${passkeyId}` });
  if (error) throw toProblem(error, response?.status);
}

export const PASSKEYS_QUERY_KEY = ["auth", "passkeys"] as const;

export function usePasskeys() {
  return useQuery({ queryKey: PASSKEYS_QUERY_KEY, queryFn: getPasskeys });
}

export function useRegisterPasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: registerPasskey,
    onSuccess: () => qc.invalidateQueries({ queryKey: PASSKEYS_QUERY_KEY }),
  });
}

export function useDeletePasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deletePasskey,
    onSuccess: () => qc.invalidateQueries({ queryKey: PASSKEYS_QUERY_KEY }),
  });
}

// --------------------------------------------------- sessions/devices + login activity (S8b)

async function getSessions(): Promise<SessionView[]> {
  const { data, error, response } = await client.get({ url: "/v1/auth/sessions" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as SessionView[];
}

async function deleteSession(familyId: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/auth/sessions/${familyId}` });
  if (error) throw toProblem(error, response?.status);
}

async function getLoginEvents(): Promise<LoginEventResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/auth/login-events" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as LoginEventResponse[];
}

export const SESSIONS_QUERY_KEY = ["auth", "sessions"] as const;
export const LOGIN_EVENTS_QUERY_KEY = ["auth", "login-events"] as const;

export function useSessions() {
  return useQuery({ queryKey: SESSIONS_QUERY_KEY, queryFn: getSessions });
}

export function useRevokeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteSession,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY });
      // Revoking the current session logs this device out; re-checking /me drives the redirect.
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useLoginEvents() {
  return useQuery({ queryKey: LOGIN_EVENTS_QUERY_KEY, queryFn: getLoginEvents });
}

// ------------------------------------------------------------------ password reset (S9a)

async function postForgotPassword(email: string): Promise<void> {
  // Always best-effort: the UI shows a generic message regardless, so neither a missing
  // address nor a transient error is observable (no enumeration / no error leak).
  try {
    await client.post({ url: "/v1/auth/password/forgot", body: { email } });
  } catch {
    /* ignore */
  }
}

async function postResetPassword(body: { token: string; password: string }): Promise<void> {
  const { error, response } = await client.post({ url: "/v1/auth/password/reset", body });
  if (error) throw toProblem(error, response?.status);
}

export function useForgotPassword() {
  return useMutation({ mutationFn: postForgotPassword });
}

export function useResetPassword() {
  return useMutation({ mutationFn: postResetPassword });
}

// ------------------------------------------------------------------ e-mail verification (S9b)

async function postRequestEmailVerification(): Promise<void> {
  await client.post({ url: "/v1/auth/email/verify/request" });
}

async function postConfirmEmail(token: string): Promise<void> {
  const { error, response } = await client.post({
    url: "/v1/auth/email/verify/confirm",
    body: { token },
  });
  if (error) throw toProblem(error, response?.status);
}

export function useRequestEmailVerification() {
  return useMutation({ mutationFn: postRequestEmailVerification });
}

export function useConfirmEmail() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postConfirmEmail,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }), // /me email_verified flips
  });
}

// ------------------------------------------------------------------ profile (If-Match) (S11)

// The profile carries its ETag (the row version) so a PATCH can send If-Match for optimistic
// concurrency; a 412 means someone else changed it first.
export type ProfileWithEtag = ProfileResponse & { etag: string };

async function fetchProfile(): Promise<ProfileWithEtag> {
  const { data, error, response } = await client.get({ url: "/v1/account/profile" });
  if (error) throw toProblem(error, response?.status);
  return { ...(data as ProfileResponse), etag: response?.headers.get("etag") ?? "" };
}

async function patchProfile(vars: {
  update: ProfileUpdate;
  etag: string;
}): Promise<ProfileWithEtag> {
  const { data, error, response } = await client.patch({
    url: "/v1/account/profile",
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return { ...(data as ProfileResponse), etag: response?.headers.get("etag") ?? "" };
}

export const PROFILE_QUERY_KEY = ["account", "profile"] as const;

export function useProfile() {
  return useQuery({ queryKey: PROFILE_QUERY_KEY, queryFn: fetchProfile });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchProfile,
    onSuccess: (data) => {
      qc.setQueryData(PROFILE_QUERY_KEY, data); // keep the fresh ETag for the next save
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY }); // display_name also shows in /me
    },
  });
}

// ----------------------------------------------------------------- child accounts (S12)

async function postCreateChild(body: CreateChildRequest): Promise<ChildResponse> {
  const { data, error, response } = await client.post({ url: "/v1/household/children", body });
  if (error) throw toProblem(error, response?.status);
  return data as ChildResponse;
}

async function postChildLogin(body: ChildLoginRequest): Promise<SessionResponse> {
  const { data, error, response } = await client.post({ url: "/v1/auth/child-login", body });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

export function useCreateChild() {
  return useMutation({ mutationFn: postCreateChild });
}

export function useChildLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postChildLogin,
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });
}

// ----------------------------------------------------------------------- households

async function getHouseholds(): Promise<HouseholdSummary[]> {
  const { data, error } = await client.get({ url: "/v1/households" });
  if (error) return [];
  return (data ?? []) as HouseholdSummary[];
}

async function postCreateHousehold(body: CreateHouseholdRequest): Promise<SessionResponse> {
  const { data, error, response } = await client.post({ url: "/v1/households", body });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

async function postSwitchHousehold(householdId: string): Promise<SessionResponse> {
  const { data, error, response } = await client.post({
    url: `/v1/households/${householdId}/switch`,
  });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

async function postJoinHousehold(body: JoinRequest): Promise<SessionResponse> {
  const { data, error, response } = await client.post({ url: "/v1/households/join", body });
  if (error) throw toProblem(error, response?.status);
  return data as SessionResponse;
}

async function postCreateInvite(): Promise<InviteResponse> {
  const { data, error, response } = await client.post({ url: "/v1/household/invites", body: {} });
  if (error) throw toProblem(error, response?.status);
  return data as InviteResponse;
}

export const HOUSEHOLDS_QUERY_KEY = ["households"] as const;

export function useHouseholds() {
  return useQuery({ queryKey: HOUSEHOLDS_QUERY_KEY, queryFn: getHouseholds });
}

// Mutations that change the active household invalidate both /me and the list.
function useSessionMutation<TVars>(mutationFn: (vars: TVars) => Promise<SessionResponse>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
      qc.invalidateQueries({ queryKey: HOUSEHOLDS_QUERY_KEY });
    },
  });
}

export function useCreateHousehold() {
  return useSessionMutation(postCreateHousehold);
}

export function useSwitchHousehold() {
  return useSessionMutation(postSwitchHousehold);
}

export function useJoinHousehold() {
  return useSessionMutation(postJoinHousehold);
}

export function useCreateInvite() {
  return useMutation({ mutationFn: postCreateInvite });
}
