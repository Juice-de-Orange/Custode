import { Trans } from "@lingui/react";
import { useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { i18n } from "../i18n";
import { useDeleteComment, useEditComment, usePostComment, useThread } from "./queries";

// A reusable comment thread for any object (KONZEPT §5.12). Embed with the object's type + id.
export function CommentThread({
  objectType,
  objectId,
}: {
  objectType: string;
  objectId: string;
}) {
  const { data: session } = useSession();
  const thread = useThread(objectType, objectId);
  const post = usePostComment();
  const edit = useEditComment();
  const remove = useDeleteComment();
  const [body, setBody] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");

  const submit = () => {
    if (!body.trim()) return;
    post.mutate(
      { objectType, objectId, bodyMd: body.trim() },
      { onSuccess: () => setBody("") },
    );
  };

  const saveEdit = (id: string, version: number) => {
    if (!editBody.trim()) return;
    edit.mutate(
      { id, bodyMd: editBody.trim(), version },
      { onSuccess: () => setEditingId(null) },
    );
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-stein-text">
        <Trans id="comments.heading" />
      </h3>
      <ul className="space-y-1">
        {thread.data?.map((c) =>
          editingId === c.id ? (
            <li key={c.id} className="flex items-start gap-2 text-sm">
              <input
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
                aria-label={i18n._("comments.edit")}
                className="flex-1 rounded border border-stein/40 bg-kalk px-2 py-1 text-sm text-tinte"
              />
              <Button
                onClick={() => saveEdit(c.id, c.version)}
                disabled={!editBody.trim() || edit.isPending}
              >
                <Trans id="comments.save" />
              </Button>
              <button
                type="button"
                onClick={() => setEditingId(null)}
                className="shrink-0 text-xs text-stein-text hover:underline"
              >
                <Trans id="comments.cancel" />
              </button>
            </li>
          ) : (
            <li key={c.id} className="flex items-start justify-between gap-2 text-sm">
              <span className="whitespace-pre-wrap text-tinte">{c.body_md}</span>
              {session?.user_id === c.author_id ? (
                <span className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(c.id);
                      setEditBody(c.body_md);
                    }}
                    className="text-xs text-bernstein hover:underline"
                  >
                    <Trans id="comments.edit" />
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate(c.id)}
                    className="text-xs text-bernstein hover:underline"
                  >
                    <Trans id="comments.delete" />
                  </button>
                </span>
              ) : null}
            </li>
          ),
        )}
        {(thread.data?.length ?? 0) === 0 ? (
          <li className="text-sm text-stein-text">
            <Trans id="comments.empty" />
          </li>
        ) : null}
      </ul>
      <div className="flex gap-2">
        <input
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={i18n._("comments.placeholder")}
          aria-label={i18n._("comments.placeholder")}
          className="flex-1 rounded border border-stein/40 bg-kalk px-2 py-1 text-sm text-tinte"
        />
        <Button onClick={submit} disabled={!body.trim() || post.isPending}>
          <Trans id="comments.send" />
        </Button>
      </div>
    </div>
  );
}
