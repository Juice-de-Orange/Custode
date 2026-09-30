import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import {
  useConfirmCapture,
  useDismissCapture,
  useInbox,
  usePostCapture,
} from "../capture/queries";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";

// Quick-Capture „Zuruf" (KONZEPT §5.17): one free-text line is parsed offline into a proposal and
// lands in the inbox; 1-tap confirm creates the item/task, dismiss discards. Auth-gated.
const TARGET_LABEL: Record<string, string> = {
  shopping: "capture.targetShopping",
  task: "capture.targetTask",
  note: "capture.targetNote",
  none: "capture.targetNone",
};

export function CapturePage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const inbox = useInbox();
  const post = usePostCapture();
  const confirm = useConfirmCapture();
  const dismiss = useDismissCapture();

  const [text, setText] = useState("");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const raw = text.trim();
    if (!raw) return;
    post.mutate({ raw_text: raw });
    setText("");
  };

  return (
    <section aria-labelledby="capture-heading" className="space-y-8">
      <h1 id="capture-heading" className="font-display text-2xl">
        <Trans id="capture.section" />
      </h1>

      {/* Zuruf input */}
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <Field
          id="zuruf"
          label={<Trans id="capture.prompt" />}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={i18n._("capture.placeholder")}
          className="min-w-64 flex-1"
        />
        <Button type="submit" disabled={post.isPending || !text.trim()}>
          <Trans id="capture.send" />
        </Button>
      </form>

      {/* Inbox of proposed captures */}
      {inbox.isLoading ? (
        <LoadingState />
      ) : inbox.isError ? (
        <ErrorState />
      ) : inbox.data && inbox.data.length > 0 ? (
        <ul className="space-y-3">
          {inbox.data.map((c) => {
            const actionable = c.proposal.target === "shopping" || c.proposal.target === "task";
            return (
              <li
                key={c.id}
                className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 p-4"
              >
                <div>
                  <span className="font-display text-lg text-tinte dark:text-kalk">{c.proposal.label}</span>
                  <span className="mt-1 block text-sm text-stein-text">
                    <span className="uppercase tracking-wide">
                      {i18n._(TARGET_LABEL[c.proposal.target] ?? "capture.targetNone")}
                    </span>
                    {c.proposal.qty ? (
                      <>
                        {" · "}
                        {c.proposal.qty}
                        {c.proposal.unit ? ` ${c.proposal.unit}` : null}
                      </>
                    ) : null}
                    {c.tags.length > 0 ? ` · ${c.tags.map((t) => `#${t}`).join(" ")}` : null}
                  </span>
                  {c.proposal.follow_up ? (
                    <span className="mt-1 block text-sm text-laurus dark:text-laurus-dark">
                      <Trans id="capture.followUp" />: {c.proposal.follow_up.label}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 gap-2">
                  {actionable ? (
                    <Button onClick={() => confirm.mutate(c.id)} disabled={confirm.isPending}>
                      <Trans id="capture.confirm" />
                    </Button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => dismiss.mutate(c.id)}
                    className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                  >
                    <Trans id="capture.dismiss" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState>
          <Trans id="capture.empty" />
        </EmptyState>
      )}
    </section>
  );
}
