import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import type { FeedbackCreate } from "../api/types.gen";
import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { useFeedback, useSubmitFeedback } from "../feedback/queries";
import { i18n } from "../i18n";
import { getDiagnostics } from "../lib/diagnostics";

const CATEGORIES: FeedbackCreate["category"][] = ["bug", "idea", "praise", "other"];

// Feedback channel (Roadmap Phase 8): a calm in-app way to send a bug/idea/praise, optionally
// tagged with the error-reference short-code the user saw, plus a list of one's own submissions.
export function FeedbackPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const feedback = useFeedback();
  const submit = useSubmitFeedback();

  const [category, setCategory] = useState<FeedbackCreate["category"]>("bug");
  const [message, setMessage] = useState("");
  const [errorRef, setErrorRef] = useState("");
  const [attachDiagnostics, setAttachDiagnostics] = useState(false);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;

  const send = () => {
    if (!message.trim()) return;
    setSent(false);
    submit.mutate(
      {
        category,
        message: message.trim(),
        error_ref: errorRef.trim() || null,
        // Strictly opt-in: only attached when the user ticked the box (technical breadcrumbs, no content).
        diagnostics: attachDiagnostics ? getDiagnostics() : null,
      },
      {
        onSuccess: () => {
          setMessage("");
          setErrorRef("");
          setSent(true);
        },
      },
    );
  };

  return (
    <section aria-labelledby="feedback-heading" className="space-y-6">
      <h1 id="feedback-heading" className="font-display text-2xl">
        <Trans id="feedback.section" />
      </h1>
      <p className="max-w-prose text-sm text-stein-text">
        <Trans id="feedback.intro" />
      </p>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-3">
          <label className="block text-sm text-stein-text">
            <Trans id="feedback.category" />
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as FeedbackCreate["category"])}
              className="mt-1 w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
              aria-label={i18n._("feedback.category")}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {i18n._(`feedback.category.${c}`)}
                </option>
              ))}
            </select>
          </label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={i18n._("feedback.messagePlaceholder")}
            rows={6}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
            aria-label={i18n._("feedback.messagePlaceholder")}
          />
          <label className="block text-sm text-stein-text">
            <Trans id="feedback.errorRef" />
            <input
              value={errorRef}
              onChange={(e) => setErrorRef(e.target.value)}
              placeholder={i18n._("feedback.errorRefPlaceholder")}
              className="mt-1 w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
              aria-label={i18n._("feedback.errorRef")}
            />
          </label>
          <label className="flex items-start gap-2 text-sm text-stein-text">
            <input
              type="checkbox"
              checked={attachDiagnostics}
              onChange={(e) => setAttachDiagnostics(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-stein/40 text-laurus dark:text-laurus-dark focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            />
            <span>
              <Trans id="feedback.diagnostics" />
            </span>
          </label>
          <div className="flex items-center gap-3">
            <Button onClick={send} disabled={!message.trim() || submit.isPending}>
              <Trans id="feedback.submit" />
            </Button>
            {sent ? (
              <span className="text-sm text-laurus dark:text-laurus-dark" role="status">
                <Trans id="feedback.sent" />
              </span>
            ) : null}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold text-stein-text">
            <Trans id="feedback.mine" />
          </h2>
          {feedback.isLoading ? (
            <LoadingState />
          ) : feedback.isError ? (
            <ErrorState />
          ) : (feedback.data?.length ?? 0) === 0 ? (
            <EmptyState>
              <Trans id="feedback.empty" />
            </EmptyState>
          ) : (
            <ul className="mt-2 space-y-2">
              {feedback.data?.map((f) => (
                <li key={f.id} className="rounded-md border border-stein/30 px-3 py-2 text-sm">
                  <span className="text-xs uppercase tracking-wide text-stein-text">
                    {i18n._(`feedback.category.${f.category}`)}
                  </span>
                  <p className="truncate text-tinte dark:text-kalk">{f.message}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
