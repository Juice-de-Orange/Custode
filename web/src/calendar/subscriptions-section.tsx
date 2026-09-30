// External CalDAV subscription management (P9, Web-Abo-Verwaltung) — the fourth section on the
// calendar page, sibling of the ICS feed block. Self-contained (own hooks, no props) like
// DigestToggle; SubscriptionCard/SubscriptionEditForm are presentational (hook-free) so the
// a11y gate and component tests can render them without a QueryClient. Credentials are
// write-only end to end: the form never prefills a password, sends the pair only when both
// fields are filled, and the wire carries has_credentials at most (ADR-0077/0080).

import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "../components/button";
import { Field } from "../components/field";
import { PasswordField } from "../components/password-field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import type { SubscriptionResponse, SubscriptionUpdate } from "../api/types.gen";
import { ProblemError } from "../lib/problem";
import { calendarProblemMessage, syncErrorId, type MessageRef } from "./errors";
import {
  useCheckSubscription,
  useCreateSubscription,
  useDeleteSubscription,
  useSubscription,
  useSubscriptions,
  useToggleSubscription,
  useUpdateSubscription,
  type SubscriptionWithEtag,
} from "./queries";

type SyncStatus = { ref: MessageRef; tone: "muted" | "error" };

// Deterministic precedence: paused beats a (stale) error, an error beats the last success.
export function syncStatus(sub: SubscriptionResponse): SyncStatus {
  const lastSync = sub.last_sync_at
    ? { time: new Date(sub.last_sync_at).toLocaleString() }
    : undefined;
  if (!sub.enabled) return { ref: { id: "calendar.subs.paused" }, tone: "muted" };
  if (sub.last_sync_error) {
    return { ref: { id: syncErrorId(sub.last_sync_error) }, tone: "error" };
  }
  if (lastSync) return { ref: { id: "calendar.subs.lastSync", values: lastSync }, tone: "muted" };
  return { ref: { id: "calendar.subs.neverSynced" }, tone: "muted" };
}

function StatusLine({ sub }: { sub: SubscriptionResponse }) {
  const status = syncStatus(sub);
  const tone = status.tone === "error" ? "text-rost dark:text-bernstein" : "text-stein-text";
  return (
    <p className={`text-sm ${tone}`}>
      {status.tone === "error" && sub.last_sync_at ? (
        <>
          <Trans
            id="calendar.subs.lastSync"
            values={{ time: new Date(sub.last_sync_at).toLocaleString() }}
          />
          {" · "}
        </>
      ) : null}
      <Trans id={status.ref.id} values={status.ref.values} />
    </p>
  );
}

/** Message for a finished probe. Success names the count so "reachable but empty" is visible;
 *  a failure reuses the sync category map, so both paths speak the same language. */
export function checkMessage(result: { ok: boolean; category: string | null; objects: number | null }): MessageRef {
  if (!result.ok) return { id: syncErrorId(result.category ?? "") };
  return { id: "calendar.subs.checkOk", values: { count: String(result.objects ?? 0) } };
}

export function SubscriptionCard({
  sub,
  pending,
  checkResult,
  onEdit,
  onToggle,
  onCheck,
  onDelete,
}: {
  sub: SubscriptionResponse;
  pending: boolean;
  checkResult?: MessageRef | null;
  onEdit: () => void;
  onToggle: () => void;
  onCheck: () => void;
  onDelete: () => void;
}) {
  return (
    <li className="space-y-1 rounded-lg border border-stein/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-display">{sub.label}</span>
        <span className="flex gap-3 text-sm">
          <button
            type="button"
            onClick={onCheck}
            disabled={pending}
            className="text-laurus dark:text-laurus-dark hover:underline"
          >
            <Trans id="calendar.subs.check" />
          </button>
          <button
            type="button"
            onClick={onEdit}
            disabled={pending}
            className="text-laurus dark:text-laurus-dark hover:underline"
          >
            <Trans id="calendar.subs.edit" />
          </button>
          <button
            type="button"
            onClick={onToggle}
            disabled={pending}
            className="text-laurus dark:text-laurus-dark hover:underline"
          >
            <Trans id={sub.enabled ? "calendar.subs.pause" : "calendar.subs.resume"} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={pending}
            className="text-bernstein-text dark:text-bernstein hover:underline"
          >
            <Trans id="calendar.subs.delete" />
          </button>
        </span>
      </div>
      <p className="truncate text-sm text-stein-text" title={sub.caldav_url}>
        {sub.caldav_url}
        {sub.has_credentials ? (
          <span className="ml-2">
            · <Trans id="calendar.subs.hasCreds" />
          </span>
        ) : null}
      </p>
      <StatusLine sub={sub} />
      {checkResult ? (
        <p role="status" className="text-sm text-stein-text">
          <Trans id={checkResult.id} values={checkResult.values} />
        </p>
      ) : null}
    </li>
  );
}

export function SubscriptionEditForm({
  initial,
  pending,
  onSubmit,
  onCancel,
}: {
  initial: SubscriptionWithEtag;
  pending: boolean;
  onSubmit: (update: SubscriptionUpdate) => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(initial.label);
  const [url, setUrl] = useState(initial.caldav_url);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [clearCreds, setClearCreds] = useState(false);
  const typingCreds = username.trim() !== "" || password.trim() !== "";

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const update: SubscriptionUpdate = { label: label.trim(), caldav_url: url.trim() };
    // Credentials replace only as a pair; empty fields keep the stored ones (write-only).
    if (username.trim() && password.trim()) {
      update.username = username.trim();
      update.password = password;
    } else if (clearCreds) {
      update.clear_credentials = true;
    }
    onSubmit(update);
  };

  return (
    <li className="rounded-lg border border-laurus/40 p-4">
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field
          id="sub-edit-label"
          label={<Trans id="calendar.subs.label" />}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          required
        />
        <Field
          id="sub-edit-url"
          label={<Trans id="calendar.subs.url" />}
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
        <Field
          id="sub-edit-username"
          label={<Trans id="calendar.subs.username" />}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="off"
        />
        <PasswordField
          id="sub-edit-password"
          label={<Trans id="calendar.subs.password" />}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
        />
        <p className="text-xs text-stein-text">
          <Trans id="calendar.subs.keepCredsHint" />
        </p>
        {initial.has_credentials ? (
          <label className="flex items-center gap-2 text-sm text-tinte dark:text-kalk">
            <input
              type="checkbox"
              checked={clearCreds && !typingCreds}
              disabled={typingCreds}
              onChange={(event) => setClearCreds(event.target.checked)}
              className="h-4 w-4 accent-laurus"
            />
            <Trans id="calendar.subs.clearCreds" />
          </label>
        ) : null}
        <div className="flex gap-2">
          <Button type="submit" disabled={pending || !label.trim() || !url.trim()}>
            <Trans id="calendar.subs.save" />
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            <Trans id="calendar.subs.cancel" />
          </Button>
        </div>
      </form>
    </li>
  );
}

export function SubscriptionsSection() {
  const subs = useSubscriptions();
  const create = useCreateSubscription();
  const update = useUpdateSubscription();
  const toggle = useToggleSubscription();
  const remove = useDeleteSubscription();
  const check = useCheckSubscription();
  // Probe results are transient per subscription — nothing is persisted, so they live here and
  // vanish on the next render cycle that clears them.
  const [checkResults, setCheckResults] = useState<Record<string, MessageRef | null>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const detail = useSubscription(editingId);
  const [error, setError] = useState<MessageRef | null>(null);
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const resetCreate = () => {
    setLabel("");
    setUrl("");
    setUsername("");
    setPassword("");
    setShowCreate(false);
  };

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    create.mutate(
      {
        label: label.trim(),
        caldav_url: url.trim(),
        // Anonymous subscription unless BOTH parts are given (backend 422s a lone half).
        ...(username.trim() && password.trim()
          ? { username: username.trim(), password }
          : {}),
      },
      {
        onSuccess: resetCreate,
        onError: (err) => setError(calendarProblemMessage(err)),
      },
    );
  };

  const pending = toggle.isPending || remove.isPending;

  return (
    <section aria-labelledby="subs-heading" className="space-y-3 border-t border-stein/20 pt-6">
      <h2 id="subs-heading" className="font-display text-lg">
        <Trans id="calendar.subs.section" />
      </h2>
      <p className="text-sm text-stein-text">
        <Trans id="calendar.subs.hint" />
      </p>

      {subs.isLoading ? (
        <LoadingState />
      ) : subs.isError ? (
        <ErrorState />
      ) : (subs.data ?? []).length === 0 && !showCreate ? (
        <EmptyState
          action={
            <Button variant="secondary" onClick={() => setShowCreate(true)}>
              <Trans id="calendar.subs.add" />
            </Button>
          }
        >
          <Trans id="calendar.subs.empty" />
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {subs.data?.map((sub) =>
            editingId === sub.id && detail.data ? (
              <SubscriptionEditForm
                key={sub.id}
                initial={detail.data}
                pending={update.isPending}
                onCancel={() => setEditingId(null)}
                onSubmit={(upd) =>
                  update.mutate(
                    { id: sub.id, etag: detail.data.etag, update: upd },
                    {
                      onSuccess: () => {
                        setEditingId(null);
                        setError(null);
                      },
                      onError: (err) => {
                        setError(calendarProblemMessage(err));
                        if (err instanceof ProblemError && err.slug === "precondition_failed") {
                          void detail.refetch(); // fresh values + ETag for the retry
                        }
                      },
                    },
                  )
                }
              />
            ) : (
              <SubscriptionCard
                key={sub.id}
                sub={sub}
                pending={pending}
                checkResult={checkResults[sub.id] ?? null}
                onCheck={() => {
                  setError(null);
                  setCheckResults((prev) => ({ ...prev, [sub.id]: null }));
                  check.mutate(sub.id, {
                    onSuccess: (result) =>
                      setCheckResults((prev) => ({ ...prev, [sub.id]: checkMessage(result) })),
                    onError: (err) => setError(calendarProblemMessage(err)),
                  });
                }}
                onEdit={() => {
                  setError(null);
                  setEditingId(sub.id);
                }}
                onToggle={() => {
                  setError(null);
                  toggle.mutate(
                    { id: sub.id, enabled: !sub.enabled },
                    { onError: (err) => setError(calendarProblemMessage(err)) },
                  );
                }}
                onDelete={() => {
                  if (!window.confirm(i18n._("calendar.subs.confirmDelete"))) return;
                  setError(null);
                  remove.mutate(sub.id, {
                    onError: (err) => setError(calendarProblemMessage(err)),
                  });
                }}
              />
            ),
          )}
        </ul>
      )}

      {error ? (
        <p role="alert" className="text-sm text-rost dark:text-bernstein">
          <Trans id={error.id} values={error.values} />
        </p>
      ) : null}

      {showCreate ? (
        <form onSubmit={handleCreate} className="space-y-3">
          <Field
            id="sub-new-label"
            label={<Trans id="calendar.subs.label" />}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            required
          />
          <Field
            id="sub-new-url"
            label={<Trans id="calendar.subs.url" />}
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://cloud.example.de/remote.php/dav/calendars/du/privat/"
            required
          />
          <Field
            id="sub-new-username"
            label={<Trans id="calendar.subs.username" />}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
          />
          <PasswordField
            id="sub-new-password"
            label={<Trans id="calendar.subs.password" />}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
          />
          <p className="text-xs text-stein-text">
            <Trans id="calendar.subs.credsHint" />
          </p>
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={create.isPending || !label.trim() || !url.trim()}
            >
              <Trans id="calendar.subs.create" />
            </Button>
            <Button type="button" variant="secondary" onClick={resetCreate}>
              <Trans id="calendar.subs.cancel" />
            </Button>
          </div>
        </form>
      ) : subs.data && subs.data.length > 0 ? (
        <Button variant="secondary" onClick={() => setShowCreate(true)}>
          <Trans id="calendar.subs.add" />
        </Button>
      ) : null}
    </section>
  );
}
