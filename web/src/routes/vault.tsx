import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { Lock } from "lucide-react";
import { useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";
import {
  decryptItemBody,
  decryptItemName,
  encryptItem,
  generateHouseholdKey,
  generateRecoveryCode,
  type ItemMeta,
  unwrapHouseholdKey,
  wrapHouseholdKey,
  type WrapMeta,
} from "../vault/crypto";
import {
  useCreateItem,
  useDeleteItem,
  usePutKey,
  useUpdateItem,
  useVaultItem,
  useVaultItems,
  useVaultKeys,
} from "../vault/queries";

// Vault (KONZEPT §5, ADR-0067): client-side end-to-end encrypted secrets. The household key lives
// only in memory (state) once unlocked; reloading the page requires unlocking again. The server
// never sees plaintext.
export function VaultPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  // Children and guests have no vault (Root-CLAUDE.md; the API answers 403). Say so instead of
  // asking and showing the generic error.
  const excluded = session?.role === "child" || session?.role === "guest";
  const keys = useVaultKeys(!!session && !excluded);
  const putKey = usePutKey();

  // The unlocked household key — in memory only, never persisted.
  const [householdKey, setHouseholdKey] = useState<Uint8Array | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryMode, setRecoveryMode] = useState(false);
  const [cameFromRecovery, setCameFromRecovery] = useState(false);

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  if (excluded) {
    return (
      <section aria-labelledby="vault-heading" className="max-w-md space-y-4">
        <h1 id="vault-heading" className="font-display text-2xl">
          <Trans id="nav.vault" />
        </h1>
        <EmptyState>
          <Trans id="vault.notForChildren" />
        </EmptyState>
      </section>
    );
  }
  if (keys.isLoading) return <LoadingState />;
  if (keys.isError) return <ErrorState />;

  const myPassphrase = (keys.data ?? []).find(
    (k) => k.kind === "passphrase" && k.member_id === session.user_id,
  );

  const recoveryEnvelope = (keys.data ?? []).find((k) => k.kind === "recovery");
  // The household's vault exists (its recovery envelope does) but this member has no envelope of
  // their own yet: they JOIN it — never set it up again. A second setup would generate a new
  // household key and try to replace the recovery envelope, which costs every other member their
  // entries and their recovery code (BUGLOG 2026-10-03; the server refuses it with 409 as well).
  const joinMode = !myPassphrase && !!recoveryEnvelope;

  // --- First-time setup: the household has no vault yet -------------------------------------
  const setup = async () => {
    setError(null);
    if (passphrase.length < 8) {
      setError("vault.error.shortPassphrase");
      return;
    }
    const key = await generateHouseholdKey();
    const code = await generateRecoveryCode();
    const passEnv = await wrapHouseholdKey(key, passphrase);
    const recEnv = await wrapHouseholdKey(key, code);
    // The recovery envelope goes first: it is the write-once claim on "this household's key".
    // If somebody else got there first (409), nothing of ours has been stored yet and the page
    // falls into join mode — the other order would leave this member with a passphrase envelope
    // around a key nobody else has.
    try {
      await putKey.mutateAsync({
        kind: "recovery",
        wrapped_key: recEnv.wrapped_key,
        wrap_meta: recEnv.wrap_meta,
      });
    } catch (err) {
      const taken = err instanceof ProblemError && err.slug === "vault_already_set_up";
      setError(taken ? "vault.error.alreadySetUp" : "state.error");
      if (taken) void keys.refetch();
      return;
    }
    // From here on the vault exists and the code is the only way in — show it whatever happens
    // to the second request.
    setRecoveryCode(code);
    try {
      await putKey.mutateAsync({
        kind: "passphrase",
        wrapped_key: passEnv.wrapped_key,
        wrap_meta: passEnv.wrap_meta,
      });
    } catch {
      // Unlocked with the key in memory, and asked to set the passphrase again (same UI as
      // after a recovery unlock).
      setCameFromRecovery(true);
    }
    setHouseholdKey(key);
    setPassphrase("");
  };

  // --- Unlock: passphrase envelope exists, key not yet in memory ----------------------------
  const unlock = async () => {
    setError(null);
    if (!myPassphrase) return;
    try {
      const key = await unwrapHouseholdKey(
        myPassphrase.wrapped_key,
        myPassphrase.wrap_meta as unknown as WrapMeta,
        passphrase,
      );
      setHouseholdKey(key);
      setPassphrase("");
    } catch {
      setError("vault.error.wrongPassphrase");
    }
  };

  // --- Recovery unlock / join: open the recovery envelope with the recovery code -------------
  // Joining is the same act as recovering: the code unwraps the existing household key, and the
  // unlocked vault then asks for an own passphrase (ChangePassphrase wraps the SAME key under
  // it). No new household key, and the recovery envelope is never written.
  const recoveryUnlock = async () => {
    setError(null);
    if (!recoveryEnvelope) return;
    try {
      const key = await unwrapHouseholdKey(
        recoveryEnvelope.wrapped_key,
        recoveryEnvelope.wrap_meta as unknown as WrapMeta,
        passphrase.trim(),
      );
      setHouseholdKey(key);
      setCameFromRecovery(true);
      setPassphrase("");
    } catch {
      setError("vault.error.wrongRecovery");
    }
  };

  // The input takes the household's recovery code (joining, or "forgot my passphrase").
  const codeEntry = joinMode || recoveryMode;

  if (householdKey === null) {
    return (
      <section aria-labelledby="vault-heading" className="max-w-md space-y-4">
        <h1 id="vault-heading" className="font-display text-2xl">
          <Trans id="nav.vault" />
        </h1>
        <p className="text-sm text-stein-text">
          <Trans
            id={
              joinMode
                ? "vault.joinHint"
                : !myPassphrase
                  ? "vault.setupHint"
                  : recoveryMode
                    ? "vault.recoveryUnlockHint"
                    : "vault.unlockHint"
            }
          />
        </p>
        <input
          type="password"
          value={passphrase}
          onChange={(e) => setPassphrase(e.target.value)}
          placeholder={i18n._(codeEntry ? "vault.recoveryCode" : "vault.passphrase")}
          aria-label={i18n._(codeEntry ? "vault.recoveryCode" : "vault.passphrase")}
          className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
        />
        {error ? (
          <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
            <Trans id={error} />
          </p>
        ) : null}
        <Button
          onClick={() =>
            void (codeEntry ? recoveryUnlock() : !myPassphrase ? setup() : unlock())
          }
          disabled={!passphrase || putKey.isPending}
        >
          <Trans id={joinMode ? "vault.join" : myPassphrase ? "vault.unlock" : "vault.setup"} />
        </Button>
        {myPassphrase && recoveryEnvelope ? (
          <button
            type="button"
            onClick={() => {
              setRecoveryMode((m) => !m);
              setError(null);
              setPassphrase("");
            }}
            className="text-sm text-laurus dark:text-laurus-dark hover:underline"
          >
            <Trans id={recoveryMode ? "vault.usePassphrase" : "vault.useRecovery"} />
          </button>
        ) : null}
        {recoveryCode ? <RecoveryNotice code={recoveryCode} /> : null}
      </section>
    );
  }

  return (
    <VaultUnlocked
      householdKey={householdKey}
      recoveryCode={recoveryCode}
      needsNewPassphrase={cameFromRecovery}
    />
  );
}

function RecoveryNotice({ code }: { code: string }) {
  return (
    <div className="rounded-lg border border-bernstein/50 bg-bernstein/5 p-3">
      <p className="text-sm font-semibold text-tinte dark:text-kalk">
        <Trans id="vault.recoveryTitle" />
      </p>
      <p className="mt-1 text-xs text-stein-text">
        <Trans id="vault.recoveryHint" />
      </p>
      <code className="mt-2 block break-all rounded bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk">
        {code}
      </code>
    </div>
  );
}

/** Standing caveat about what leaving a household does *not* do to the vault key.
 *
 *  KONZEPT §5.1 asks for a warning during lazy re-encryption. There is no re-encryption yet, so
 *  the honest text is about the gap itself: the household key is derived from a shared passphrase,
 *  a departure does not change it, and anyone who memorised it keeps the ability to decrypt. The
 *  one thing a household can actually do about that is in the second sentence — change the
 *  passphrase, which the button right below this notice does. */
function ExitRotationNotice() {
  return (
    <div className="max-w-md rounded-lg border border-rost/40 bg-rost/5 p-3">
      <p className="text-sm font-semibold text-tinte dark:text-kalk">
        <Trans id="vault.exitNoticeTitle" />
      </p>
      <p className="mt-1 text-xs text-stein-text">
        <Trans id="vault.exitNoticeBody" />
      </p>
    </div>
  );
}

// The unlocked vault: a list of secrets (names decrypted client-side) plus add/view/delete.
function VaultUnlocked({
  householdKey,
  recoveryCode,
  needsNewPassphrase,
}: {
  householdKey: Uint8Array;
  recoveryCode: string | null;
  needsNewPassphrase: boolean;
}) {
  const items = useVaultItems();
  const createItem = useCreateItem();
  const deleteItem = useDeleteItem();
  const [names, setNames] = useState<Record<string, string>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");

  // Decrypt each item's name (from item_meta) for the list view.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const out: Record<string, string> = {};
      for (const item of items.data ?? []) {
        try {
          out[item.id] = await decryptItemName(
            item.item_meta as unknown as ItemMeta,
            householdKey,
          );
        } catch {
          out[item.id] = "??";
        }
      }
      if (!cancelled) setNames(out);
    })();
    return () => {
      cancelled = true;
    };
  }, [items.data, householdKey]);

  const add = async () => {
    if (!name.trim() || !secret) return;
    const enc = await encryptItem(name.trim(), secret, householdKey);
    await createItem.mutateAsync({ ciphertext: enc.ciphertext, item_meta: enc.item_meta });
    setName("");
    setSecret("");
  };

  return (
    <section aria-labelledby="vault-heading" className="space-y-6">
      <h1 id="vault-heading" className="font-display text-2xl">
        <Trans id="nav.vault" />
      </h1>
      {recoveryCode ? <RecoveryNotice code={recoveryCode} /> : null}

      {/* KONZEPT §5.1 promises key rotation when somebody leaves ("bis dahin Warnhinweis im
          Vault"). The rotation is not built — it needs a per-member asymmetric identity and its
          own ADR (docs/MODULES/vault.md). So the notice cannot say "we are re-encrypting"; it has
          to say the true thing, which is worse and actionable: a departed member who kept the
          passphrase can still read anything stored before they left. Standing text rather than a
          reaction to a departure, because the limitation is standing. */}
      <ExitRotationNotice />

      <ChangePassphrase householdKey={householdKey} highlight={needsNewPassphrase} />

      <div className="max-w-md space-y-2 rounded-lg border border-stein/30 p-4">
        <h2 className="text-sm font-semibold text-stein-text">
          <Trans id="vault.add" />
        </h2>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={i18n._("vault.name")}
          aria-label={i18n._("vault.name")}
          className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
        />
        <textarea
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder={i18n._("vault.secret")}
          aria-label={i18n._("vault.secret")}
          rows={3}
          className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk"
        />
        <Button onClick={() => void add()} disabled={!name.trim() || !secret || createItem.isPending}>
          <Trans id="vault.save" />
        </Button>
      </div>

      <div className="max-w-md">
        {items.isLoading ? (
          <LoadingState />
        ) : items.isError ? (
          <ErrorState />
        ) : (items.data?.length ?? 0) === 0 ? (
          <EmptyState>
            <Trans id="vault.empty" />
          </EmptyState>
        ) : (
          <ul className="space-y-1">
            {items.data?.map((item) => (
              <li key={item.id} className="rounded-md border border-stein/30 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => setOpenId(openId === item.id ? null : item.id)}
                    className="flex items-center gap-1.5 truncate text-left text-sm text-tinte hover:underline dark:text-kalk"
                  >
                    <Lock className="size-3.5 shrink-0 text-laurus dark:text-laurus-dark" aria-hidden="true" />
                    <span className="truncate">{names[item.id] ?? "…"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteItem.mutate(item.id)}
                    className="shrink-0 text-xs text-bernstein-text dark:text-bernstein hover:underline"
                  >
                    <Trans id="vault.delete" />
                  </button>
                </div>
                {openId === item.id ? (
                  <SecretReveal
                    id={item.id}
                    householdKey={householdKey}
                    initialName={names[item.id] ?? ""}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// Fetches the full item and decrypts the secret body on demand. Supports inline editing: the name
// + body are re-encrypted client-side and saved via PATCH + If-Match (the fetched item carries the
// ETag), so a concurrent change is rejected with 412 rather than silently overwritten.
function SecretReveal({
  id,
  householdKey,
  initialName,
}: {
  id: string;
  householdKey: Uint8Array;
  initialName: string;
}) {
  const item = useVaultItem(id);
  const update = useUpdateItem();
  const [body, setBody] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(initialName);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!item.data) return;
    void (async () => {
      try {
        const text = await decryptItemBody(
          item.data!.ciphertext,
          item.data!.item_meta as unknown as ItemMeta,
          householdKey,
        );
        if (!cancelled) setBody(text);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.data, householdKey]);

  const save = async () => {
    if (!item.data || !draft) return;
    const enc = await encryptItem(name.trim() || initialName, draft, householdKey);
    await update.mutateAsync({
      id,
      update: { ciphertext: enc.ciphertext, item_meta: enc.item_meta },
      etag: item.data.etag,
    });
    setEditing(false);
  };

  if (item.isLoading) return <LoadingState />;
  if (failed) return <ErrorState />;

  if (editing) {
    return (
      <div className="mt-2 space-y-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label={i18n._("vault.name")}
          className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
        />
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label={i18n._("vault.secret")}
          rows={3}
          className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk"
        />
        <div className="flex gap-2">
          <Button onClick={() => void save()} disabled={!draft || update.isPending}>
            <Trans id="vault.save" />
          </Button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="text-sm text-stein-text hover:underline"
          >
            <Trans id="vault.cancel" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1">
      <pre className="whitespace-pre-wrap break-all rounded bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk">
        {body ?? "…"}
      </pre>
      {body !== null ? (
        <button
          type="button"
          onClick={() => {
            setName(initialName);
            setDraft(body);
            setEditing(true);
          }}
          className="text-xs text-laurus dark:text-laurus-dark hover:underline"
        >
          <Trans id="vault.edit" />
        </button>
      ) : null}
    </div>
  );
}

// Set or change the vault passphrase: re-wrap the (already unlocked) household key under a new
// passphrase and store the envelope. Used both after a recovery unlock and to rotate the passphrase.
function ChangePassphrase({
  householdKey,
  highlight,
}: {
  householdKey: Uint8Array;
  highlight: boolean;
}) {
  const putKey = usePutKey();
  const [open, setOpen] = useState(highlight);
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const save = async () => {
    setError(null);
    if (next.length < 8) {
      setError("vault.error.shortPassphrase");
      return;
    }
    const env = await wrapHouseholdKey(householdKey, next);
    await putKey.mutateAsync({
      kind: "passphrase",
      wrapped_key: env.wrapped_key,
      wrap_meta: env.wrap_meta,
    });
    setNext("");
    setDone(true);
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="text-sm text-laurus dark:text-laurus-dark hover:underline">
        <Trans id="vault.changePassphrase" />
      </button>
    );
  }

  return (
    <div
      className={`max-w-md space-y-2 rounded-lg border p-4 ${
        highlight ? "border-bernstein/50 bg-bernstein/5" : "border-stein/30"
      }`}
    >
      <h2 className="text-sm font-semibold text-stein-text">
        <Trans id={highlight ? "vault.setNewPassphrase" : "vault.changePassphrase"} />
      </h2>
      <input
        type="password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        placeholder={i18n._("vault.passphrase")}
        aria-label={i18n._("vault.passphrase")}
        className="w-full rounded border border-stein/40 bg-kalk px-2 py-1 text-tinte"
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      {done ? (
        <p role="status" className="text-sm text-laurus dark:text-laurus-dark">
          <Trans id="vault.passphraseSaved" />
        </p>
      ) : null}
      <Button onClick={() => void save()} disabled={!next || putKey.isPending}>
        <Trans id="vault.save" />
      </Button>
    </div>
  );
}
