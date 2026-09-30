import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import type { TaskTemplateSummary } from "../api/types.gen";
import { useSession } from "../auth/session";
import { useBalance } from "../economy/queries";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { countMyOverdue, hasBottleneck } from "../tasks/bottleneck";
import { effectivePoints, isOverdue } from "../tasks/decay";
import { i18n } from "../i18n";
import {
  type InstanceWithEtag,
  useCompleteInstance,
  useCreateInstance,
  useCreateTemplate,
  useDeleteTemplate,
  useRooms,
  useTaskInstances,
  useTaskTemplates,
} from "../tasks/queries";

// One open task row with its "complete" action (open -> done; If-Match guarded). Exported for tests.
export function TaskRow({
  instance,
  onComplete,
  pending,
}: {
  instance: InstanceWithEtag;
  onComplete: (instance: InstanceWithEtag) => void;
  pending: boolean;
}) {
  const overdue = isOverdue(instance.due_at);
  const worth = overdue ? effectivePoints(instance.points, instance.due_at) : instance.points;
  return (
    <li className="flex items-center justify-between gap-4 rounded-lg border border-stein/30 p-4">
      <div>
        <span className="font-display text-lg text-tinte dark:text-kalk">{instance.title}</span>
        <span className="mt-1 block text-sm text-stein-text">
          {instance.points > 0 ? (
            <span>
              {worth} <Trans id="tasks.pointsUnit" />
              {overdue && worth < instance.points ? (
                <span className="ml-1 text-bernstein-text dark:text-bernstein">
                  (<Trans id="tasks.wasWorth" /> {instance.points})
                </span>
              ) : null}
            </span>
          ) : null}
          {overdue ? (
            <span className="ml-2 rounded bg-bernstein/15 px-2 py-0.5 text-xs text-bernstein-text dark:text-bernstein">
              <Trans id="tasks.overdue" />
            </span>
          ) : null}
          {instance.assigned_to ? (
            <span className="ml-2 rounded bg-stein/15 px-2 py-0.5 text-xs">
              <Trans id="tasks.assigned" />
            </span>
          ) : null}
        </span>
      </div>
      <Button onClick={() => onComplete(instance)} disabled={pending}>
        <Trans id="tasks.complete" />
      </Button>
    </li>
  );
}

// Haushaltsaufgaben (KONZEPT §5.9): open instances with a 1-tap "done", plus forms to create an
// instance (from a template or ad-hoc) and — for admins — to author templates. Auth-gated.
export function TasksPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const balance = useBalance();
  const instances = useTaskInstances();
  const templates = useTaskTemplates();
  const createInstance = useCreateInstance();
  const completeInstance = useCompleteInstance();
  const createTemplate = useCreateTemplate();
  const deleteTemplate = useDeleteTemplate();

  const rooms = useRooms();
  const [adHocTitle, setAdHocTitle] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [tplTitle, setTplTitle] = useState("");
  const [tplPoints, setTplPoints] = useState("0");
  const [tplRoom, setTplRoom] = useState("");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  const isAdmin = session.role === "admin";

  const handleComplete = (instance: InstanceWithEtag) =>
    completeInstance.mutate({ id: instance.id, etag: instance.etag });

  const handleCreateInstance = (event: FormEvent) => {
    event.preventDefault();
    if (templateId) createInstance.mutate({ template_id: templateId });
    else if (adHocTitle.trim()) createInstance.mutate({ title: adHocTitle.trim() });
    setAdHocTitle("");
    setTemplateId("");
  };

  const handleCreateTemplate = (event: FormEvent) => {
    event.preventDefault();
    if (!tplTitle.trim()) return;
    createTemplate.mutate({
      title: tplTitle.trim(),
      points: Number(tplPoints) || 0,
      room_id: tplRoom || null,
    });
    setTplTitle("");
    setTplRoom("");
    setTplPoints("0");
  };

  return (
    <section aria-labelledby="tasks-heading" className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <h1 id="tasks-heading" className="font-display text-2xl">
          <Trans id="tasks.section" />
        </h1>
        {balance.data ? (
          <span
            className="shrink-0 rounded-full bg-laurus/10 px-3 py-1 text-sm font-medium text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark"
            aria-label={i18n._("tasks.balance")}
          >
            {balance.data.balance} <Trans id="tasks.pointsUnit" />
          </span>
        ) : null}
      </div>

      {/* S-10: a pile of my own overdue tasks nudges toward offering some on the marketplace. */}
      {hasBottleneck(countMyOverdue(instances.data ?? [], session.user_id)) ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-bernstein/40 bg-bernstein/10 px-3 py-2 text-sm">
          <span className="text-tinte dark:text-kalk">
            {i18n._("tasks.bottleneck", {
              count: countMyOverdue(instances.data ?? [], session.user_id),
            })}
          </span>
          <button
            type="button"
            onClick={() => void navigate({ to: "/marketplace" })}
            className="font-medium text-bernstein-text dark:text-bernstein hover:underline"
          >
            <Trans id="tasks.offerOnMarket" />
          </button>
        </div>
      ) : null}

      {/* Open instances */}
      <section aria-labelledby="open-heading" className="space-y-3">
        <h2 id="open-heading" className="font-display text-lg">
          <Trans id="tasks.open" />
        </h2>
        {instances.isLoading ? (
          <LoadingState />
        ) : instances.isError ? (
          <ErrorState />
        ) : instances.data && instances.data.length > 0 ? (
          <ul className="space-y-3">
            {instances.data.map((instance) => (
              <TaskRow
                key={instance.id}
                instance={instance}
                onComplete={handleComplete}
                pending={completeInstance.isPending}
              />
            ))}
          </ul>
        ) : (
          <EmptyState>
            <Trans id="tasks.empty" />
          </EmptyState>
        )}
      </section>

      {/* Create an instance (from a template or ad-hoc) */}
      <section aria-labelledby="add-heading" className="space-y-3">
        <h2 id="add-heading" className="font-display text-lg">
          <Trans id="tasks.addInstance" />
        </h2>
        <form onSubmit={handleCreateInstance} className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="task-template" className="block text-sm font-medium text-tinte dark:text-kalk">
              <Trans id="tasks.fromTemplate" />
            </label>
            <select
              id="task-template"
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              className="block w-full rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            >
              <option value="">{i18n._("tasks.adHoc")}</option>
              {templates.data?.map((t: TaskTemplateSummary) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </div>
          {!templateId ? (
            <Field
              id="task-adhoc"
              label={<Trans id="tasks.adHocTitle" />}
              value={adHocTitle}
              onChange={(e) => setAdHocTitle(e.target.value)}
              placeholder={i18n._("tasks.adHocPlaceholder")}
            />
          ) : null}
          <Button type="submit" disabled={createInstance.isPending || (!templateId && !adHocTitle.trim())}>
            <Trans id="tasks.addInstance" />
          </Button>
        </form>
      </section>

      {/* Author templates (admin only) */}
      {isAdmin ? (
        <section aria-labelledby="templates-heading" className="space-y-3">
          <h2 id="templates-heading" className="font-display text-lg">
            <Trans id="tasks.templates" />
          </h2>
          <form onSubmit={handleCreateTemplate} className="space-y-3">
            <Field
              id="tpl-title"
              label={<Trans id="tasks.templateTitle" />}
              value={tplTitle}
              onChange={(e) => setTplTitle(e.target.value)}
            />
            <Field
              id="tpl-points"
              type="number"
              min={0}
              label={<Trans id="tasks.templatePoints" />}
              value={tplPoints}
              onChange={(e) => setTplPoints(e.target.value)}
            />
            {rooms.data && rooms.data.length > 0 ? (
              <div className="space-y-1">
                <label htmlFor="tpl-room" className="block text-sm font-medium text-tinte dark:text-kalk">
                  <Trans id="nav.rooms" />
                </label>
                <select
                  id="tpl-room"
                  value={tplRoom}
                  onChange={(e) => setTplRoom(e.target.value)}
                  className="block w-full rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
                >
                  <option value="">{i18n._("rooms.none")}</option>
                  {rooms.data.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <Button type="submit" disabled={createTemplate.isPending || !tplTitle.trim()}>
              <Trans id="tasks.addTemplate" />
            </Button>
          </form>
          {templates.data && templates.data.length > 0 ? (
            <ul className="space-y-2">
              {templates.data.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-4 rounded-md border border-stein/20 px-3 py-2"
                >
                  <span className="text-tinte dark:text-kalk">
                    {t.title}
                    {t.points > 0 ? <span className="ml-2 text-sm text-stein-text">{t.points} P</span> : null}
                  </span>
                  <button
                    type="button"
                    onClick={() => deleteTemplate.mutate(t.id)}
                    className="text-sm text-bernstein-text dark:text-bernstein hover:underline"
                  >
                    <Trans id="tasks.deleteTemplate" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
