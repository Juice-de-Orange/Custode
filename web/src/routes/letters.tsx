import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";

import { useSession } from "../auth/session";
import { CommentThread } from "../comments/thread";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { useHouseholdMembers } from "../economy/queries";
import { i18n } from "../i18n";
import {
  LETTERS_QUERY_KEY,
  useConvertToTask,
  useInbox,
  useLetter,
  useSendLetter,
} from "../messaging/queries";

// Messaging / „Briefe" (KONZEPT §5.12): calm asynchronous letters with a read status. Pick
// recipients, or leave empty for a round-letter to the whole household. Notifications are later.
export function LettersPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: session, isLoading: sessionLoading } = useSession();
  const inbox = useInbox();
  const sendLetter = useSendLetter();
  const convertToTask = useConvertToTask();
  const [convertMsg, setConvertMsg] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useLetter(selectedId);

  const [composing, setComposing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [recipients, setRecipients] = useState<string[]>([]);
  const members = useHouseholdMembers();

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  // Opening a letter marks it read server-side -> refresh the inbox + unread badge.
  useEffect(() => {
    if (selected.data?.read_by_me) qc.invalidateQueries({ queryKey: LETTERS_QUERY_KEY });
  }, [selected.data?.read_by_me, qc]);

  if (sessionLoading || !session) return <LoadingState />;

  // Recipients other than yourself; empty selection = round-letter to the whole household.
  const otherMembers = (members.data ?? []).filter((m) => m.user_id !== session.user_id);

  const toggleRecipient = (userId: string) => {
    setRecipients((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );
  };

  const send = () => {
    if (!subject.trim()) return;
    sendLetter.mutate(
      { subject: subject.trim(), body_md: body, to_ids: recipients },
      {
        onSuccess: () => {
          setComposing(false);
          setSubject("");
          setBody("");
          setRecipients([]);
        },
      },
    );
  };

  return (
    <section aria-labelledby="letters-heading" className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 id="letters-heading" className="font-display text-2xl">
          <Trans id="letters.section" />
        </h1>
        <Button onClick={() => setComposing((c) => !c)}>
          <Trans id="letters.compose" />
        </Button>
      </div>

      {composing ? (
        <div className="space-y-2 rounded-lg border border-stein/30 p-4">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={i18n._("letters.subject")}
            aria-label={i18n._("letters.subject")}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={i18n._("letters.body")}
            aria-label={i18n._("letters.body")}
            rows={5}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
          />
          {otherMembers.length > 0 ? (
            <fieldset className="space-y-1">
              <legend className="text-xs font-semibold text-stein-text">
                <Trans id="letters.recipients" />
              </legend>
              <div className="flex flex-wrap gap-3">
                {otherMembers.map((m) => (
                  <label key={m.user_id} className="flex items-center gap-1 text-sm text-tinte dark:text-kalk">
                    <input
                      type="checkbox"
                      checked={recipients.includes(m.user_id)}
                      onChange={() => toggleRecipient(m.user_id)}
                    />
                    {m.display_name}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}
          <p className="text-xs text-stein-text">
            <Trans
              id={recipients.length === 0 ? "letters.broadcastHint" : "letters.addressedHint"}
            />
          </p>
          <Button onClick={send} disabled={!subject.trim() || sendLetter.isPending}>
            <Trans id="letters.send" />
          </Button>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <div>
          {inbox.isLoading ? (
            <LoadingState />
          ) : inbox.isError ? (
            <ErrorState />
          ) : (inbox.data?.length ?? 0) === 0 ? (
            <EmptyState>
              <Trans id="letters.empty" />
            </EmptyState>
          ) : (
            <ul className="space-y-2">
              {inbox.data?.map((l) => (
                <li key={l.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(l.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm ${
                      l.id === selectedId
                        ? "border-laurus bg-laurus/5"
                        : "border-stein/30 hover:border-laurus"
                    }`}
                  >
                    <span className="flex items-center gap-2 truncate">
                      {!l.read_by_me ? (
                        <span
                          aria-label={i18n._("letters.unread")}
                          className="h-2 w-2 shrink-0 rounded-full bg-laurus"
                        />
                      ) : null}
                      <span className="truncate text-tinte dark:text-kalk">{l.subject}</span>
                    </span>
                    <span className="shrink-0 text-xs text-stein-text">{l.read_count} <Check className="size-4" aria-hidden="true" /></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          {selected.data ? (
            <article className="space-y-2 rounded-lg border border-stein/30 p-4">
              <h2 className="font-display text-lg text-tinte dark:text-kalk">{selected.data.subject}</h2>
              <p className="whitespace-pre-wrap text-sm text-tinte dark:text-kalk">{selected.data.body_md}</p>
              <p className="text-xs text-stein-text">
                {i18n._("letters.readBy", { count: selected.data.read_count })}
              </p>
              <div className="flex items-center gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setConvertMsg(null);
                    convertToTask.mutate(selected.data!.id, {
                      onSuccess: () => setConvertMsg(i18n._("letters.converted")),
                    });
                  }}
                  disabled={convertToTask.isPending}
                  className="text-sm text-laurus dark:text-laurus-dark hover:underline"
                >
                  <Trans id="letters.toTask" />
                </button>
                {convertMsg ? (
                  <span className="text-sm text-laurus dark:text-laurus-dark" role="status">
                    {convertMsg}
                  </span>
                ) : null}
              </div>
              <div className="border-t border-stein/20 pt-3">
                <CommentThread objectType="letter" objectId={selected.data.id} />
              </div>
            </article>
          ) : (
            <EmptyState>
              <Trans id="letters.pick" />
            </EmptyState>
          )}
        </div>
      </div>
    </section>
  );
}
