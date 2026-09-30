import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { CommentThread } from "../comments/thread";
import { AttachmentsPanel } from "../guides/attachments-panel";
import { LinksPanel } from "../links/panel";
import { Button } from "../components/button";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { useHouseholdMembers } from "../economy/queries";
import {
  useCreateGuide,
  useDeleteGuide,
  useGuide,
  useGuides,
  useUpdateGuide,
} from "../guides/queries";
import { i18n } from "../i18n";

// Guides / „Anleitungen" (KONZEPT §5): household markdown guides with a category, tags and German
// full-text search. Attachments, ACL and contacts are later slices.
export function GuidesPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const [q, setQ] = useState("");
  const guides = useGuides(q);
  const createGuide = useCreateGuide();
  const updateGuide = useUpdateGuide();
  const deleteGuide = useDeleteGuide();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useGuide(selectedId);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState("");
  const [contact, setContact] = useState<string>("");
  const members = useHouseholdMembers();

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  useEffect(() => {
    if (selected.data) {
      setTitle(selected.data.title);
      setBody(selected.data.body_md);
      setCategory(selected.data.category);
      setContact(selected.data.contact_id ?? "");
    }
  }, [selected.data]);

  if (sessionLoading || !session) return <LoadingState />;

  const startNew = () => {
    setSelectedId(null);
    setTitle("");
    setBody("");
    setCategory("");
    setContact("");
  };

  const save = () => {
    if (!title.trim()) return;
    // "" in the picker means "no contact" -> send null to clear it server-side.
    const contactId = contact || null;
    if (selectedId && selected.data) {
      updateGuide.mutate({
        id: selectedId,
        update: { title: title.trim(), body_md: body, category, contact_id: contactId },
        etag: selected.data.etag,
      });
    } else {
      createGuide.mutate(
        { title: title.trim(), body_md: body, category, contact_id: contactId },
        { onSuccess: (g) => setSelectedId((g as { id: string }).id) },
      );
    }
  };

  const remove = () => {
    if (selectedId) deleteGuide.mutate(selectedId, { onSuccess: startNew });
  };

  return (
    <section aria-labelledby="guides-heading" className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 id="guides-heading" className="font-display text-2xl">
          <Trans id="guides.section" />
        </h1>
        <Button onClick={startNew}>
          <Trans id="guides.new" />
        </Button>
      </div>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={i18n._("guides.search")}
        aria-label={i18n._("guides.search")}
        className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <div>
          {guides.isLoading ? (
            <LoadingState />
          ) : guides.isError ? (
            <ErrorState />
          ) : (guides.data?.length ?? 0) === 0 ? (
            <EmptyState>
              <Trans id="guides.empty" />
            </EmptyState>
          ) : (
            <ul className="space-y-2">
              {guides.data?.map((g) => (
                <li key={g.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(g.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm ${
                      g.id === selectedId
                        ? "border-laurus bg-laurus/5"
                        : "border-stein/30 hover:border-laurus"
                    }`}
                  >
                    <span className="truncate text-tinte dark:text-kalk">{g.title}</span>
                    {g.category ? (
                      <span className="shrink-0 text-xs text-stein-text">{g.category}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={i18n._("guides.titlePlaceholder")}
            aria-label={i18n._("guides.titlePlaceholder")}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-tinte dark:text-kalk"
          />
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder={i18n._("guides.categoryPlaceholder")}
            aria-label={i18n._("guides.categoryPlaceholder")}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
          />
          <select
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            aria-label={i18n._("guides.contact")}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 text-sm text-tinte dark:text-kalk"
          >
            <option value="">{i18n._("guides.contactNone")}</option>
            {members.data?.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name}
              </option>
            ))}
          </select>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={i18n._("guides.bodyPlaceholder")}
            aria-label={i18n._("guides.bodyPlaceholder")}
            rows={14}
            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-2 py-1 font-mono text-sm text-tinte dark:text-kalk"
          />
          <div className="flex gap-2">
            <Button
              onClick={save}
              disabled={!title.trim() || createGuide.isPending || updateGuide.isPending}
            >
              <Trans id="guides.save" />
            </Button>
            {selectedId ? (
              <button
                type="button"
                onClick={remove}
                disabled={deleteGuide.isPending}
                className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
              >
                <Trans id="guides.delete" />
              </button>
            ) : null}
          </div>

          {/* File attachments of the selected guide (KONZEPT §5, P7-S22). */}
          {selectedId ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <AttachmentsPanel guideId={selectedId} />
            </div>
          ) : null}

          {/* Links from the selected guide to other objects (KONZEPT §5.12, generic links). */}
          {selectedId ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <LinksPanel objectType="guide" objectId={selectedId} />
            </div>
          ) : null}

          {/* Comments on the selected guide (KONZEPT §5.12, generic object thread). */}
          {selectedId ? (
            <div className="mt-4 border-t border-stein/20 pt-3">
              <CommentThread objectType="guide" objectId={selectedId} />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
