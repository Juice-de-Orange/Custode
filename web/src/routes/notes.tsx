import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { Pin } from "lucide-react";
import { useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { CommentThread } from "../comments/thread";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { LinksPanel } from "../links/panel";
import {
  useConvertToTask,
  useCreateNote,
  useDeleteNote,
  useNote,
  useNoteVersions,
  useNotes,
  useRestoreVersion,
  useTrashedNotes,
  useUntrashNote,
  useUpdateNote,
} from "../notes/queries";

// Notes (KONZEPT §5 / Phase 7): manual markdown notes with a dashboard pin. Version history,
// convert-to and the dashboard pin view come in later slices.
export function NotesPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const notes = useNotes();
  const createNote = useCreateNote();
  const updateNote = useUpdateNote();
  const deleteNote = useDeleteNote();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useNote(selectedId);
  const versions = useNoteVersions(selectedId);
  const restoreVersion = useRestoreVersion();
  const convertToTask = useConvertToTask();
  const [convertMsg, setConvertMsg] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [pinned, setPinned] = useState(false);

  const [showTrash, setShowTrash] = useState(false);
  const trash = useTrashedNotes();
  const untrashNote = useUntrashNote();

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  // Load the selected note's fields into the editor when it arrives.
  useEffect(() => {
    if (selected.data) {
      setTitle(selected.data.title);
      setBody(selected.data.body_md);
      setPinned(selected.data.pinned);
    }
  }, [selected.data]);

  if (sessionLoading || !session) return <LoadingState />;

  const startNew = () => {
    setSelectedId(null);
    setTitle("");
    setBody("");
    setPinned(false);
  };

  const save = () => {
    if (!title.trim()) return;
    if (selectedId && selected.data) {
      updateNote.mutate({
        id: selectedId,
        update: { title: title.trim(), body_md: body, pinned },
        etag: selected.data.etag,
      });
    } else {
      createNote.mutate(
        { title: title.trim(), body_md: body, pinned },
        { onSuccess: (n) => setSelectedId((n as { id: string }).id) },
      );
    }
  };

  const remove = () => {
    if (selectedId) deleteNote.mutate(selectedId, { onSuccess: startNew });
  };

  return (
    <section aria-labelledby="notes-heading" className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 id="notes-heading" className="font-display text-2xl">
          <Trans id="notes.section" />
        </h1>
        <Button onClick={startNew}>
          <Trans id="notes.new" />
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <div>
          {notes.isLoading ? (
            <LoadingState />
          ) : notes.isError ? (
            <ErrorState />
          ) : (notes.data?.length ?? 0) === 0 ? (
            <EmptyState>
              <Trans id="notes.empty" />
            </EmptyState>
          ) : (
            <ul className="space-y-2">
              {notes.data?.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(n.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm ${
                      n.id === selectedId
                        ? "border-laurus bg-laurus/5"
                        : "border-stein/30 hover:border-laurus"
                    }`}
                  >
                    <span className="truncate text-tinte dark:text-kalk">{n.title}</span>
                    {n.pinned ? (
                      <span title={i18n._("notes.pinned")}>
                        <Pin className="size-4" aria-hidden="true" />
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Papierkorb (P8-S4): soft-deleted notes, restorable until the reaper purges them
              after 30 days (P8-S3). Collapsed by default to keep the list calm. */}
          <div className="mt-4 border-t border-stein/20 pt-3">
            <button
              type="button"
              onClick={() => setShowTrash((v) => !v)}
              aria-expanded={showTrash}
              className="text-sm text-stein-text hover:text-tinte"
            >
              <Trans id="notes.trash.toggle" /> ({trash.data?.length ?? 0})
            </button>
            {showTrash ? (
              trash.isLoading ? (
                <LoadingState />
              ) : trash.isError ? (
                <ErrorState />
              ) : (trash.data?.length ?? 0) === 0 ? (
                <EmptyState>
                  <Trans id="notes.trash.empty" />
                </EmptyState>
              ) : (
                <>
                  <p className="mt-2 text-xs text-stein-text">
                    <Trans id="notes.trash.hint" />
                  </p>
                  <ul className="mt-2 space-y-1">
                    {trash.data?.map((n) => (
                      <li key={n.id} className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate text-stein-text">{n.title}</span>
                        <button
                          type="button"
                          onClick={() => untrashNote.mutate(n.id)}
                          disabled={untrashNote.isPending}
                          className="shrink-0 text-laurus dark:text-laurus-dark hover:underline"
                        >
                          <Trans id="notes.trash.restore" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )
            ) : null}
          </div>
        </div>

        <div className="space-y-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={i18n._("notes.titlePlaceholder")}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
            aria-label={i18n._("notes.titlePlaceholder")}
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={i18n._("notes.bodyPlaceholder")}
            rows={12}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk"
            aria-label={i18n._("notes.bodyPlaceholder")}
          />
          <label className="flex items-center gap-2 text-sm text-stein-text">
            <input
              type="checkbox"
              checked={pinned}
              onChange={(e) => setPinned(e.target.checked)}
            />
            <Trans id="notes.pin" />
          </label>
          <div className="flex gap-2">
            <Button onClick={save} disabled={!title.trim() || createNote.isPending || updateNote.isPending}>
              <Trans id="notes.save" />
            </Button>
            {selectedId ? (
              <button
                type="button"
                onClick={() => {
                  setConvertMsg(null);
                  convertToTask.mutate(selectedId, {
                    onSuccess: () => setConvertMsg(i18n._("notes.converted")),
                  });
                }}
                disabled={convertToTask.isPending}
                className="text-sm text-laurus dark:text-laurus-dark hover:underline"
              >
                <Trans id="notes.toTask" />
              </button>
            ) : null}
            {selectedId ? (
              <button
                type="button"
                onClick={remove}
                disabled={deleteNote.isPending}
                className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
              >
                <Trans id="notes.delete" />
              </button>
            ) : null}
            {convertMsg ? (
              <span className="text-sm text-laurus dark:text-laurus-dark" role="status">
                {convertMsg}
              </span>
            ) : null}
          </div>

          {/* Version history (P7-S2): up to 5 prior versions, newest first; restore in one click. */}
          {selectedId && (versions.data?.length ?? 0) > 0 ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <h2 className="text-sm font-semibold text-stein-text">
                <Trans id="notes.versions" />
              </h2>
              <ul className="mt-2 space-y-1">
                {versions.data?.map((v) => (
                  <li
                    key={v.version_no}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <span className="truncate text-tinte dark:text-kalk">
                      v{v.version_no} · {v.title}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        restoreVersion.mutate({ id: selectedId, versionNo: v.version_no })
                      }
                      disabled={restoreVersion.isPending}
                      className="shrink-0 text-laurus dark:text-laurus-dark hover:underline"
                    >
                      <Trans id="notes.restore" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* Links + comments on the selected note (KONZEPT §5.12, generic object panels). */}
          {selectedId ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <LinksPanel objectType="note" objectId={selectedId} />
            </div>
          ) : null}
          {selectedId ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <CommentThread objectType="note" objectId={selectedId} />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
