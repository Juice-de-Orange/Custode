import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { useCreateInstance, useCreateRoom, useDeleteRoom, useHeatmap } from "../tasks/queries";

const STATUS_CLASS: Record<string, string> = {
  green: "border-laurus/40 bg-laurus/10",
  amber: "border-bernstein/40 bg-bernstein/10",
  red: "border-rost/40 bg-rost/10",
};
const STATUS_DOT: Record<string, string> = {
  green: "bg-laurus",
  amber: "bg-bernstein",
  red: "bg-rost",
};

// Raum-Heatmap (KONZEPT §5.9/§5.8): each room's freshness from its tasks' last completion. Admins
// manage rooms; everyone sees the heatmap. Auth-gated.
export function RoomsPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const heatmap = useHeatmap();
  const createRoom = useCreateRoom();
  const deleteRoom = useDeleteRoom();
  const createInstance = useCreateInstance();

  const [name, setName] = useState("");
  const [decayDays, setDecayDays] = useState("7");
  // The room a task is being added to (its id) + the task title (S-13 heatmap action).
  const [addingRoom, setAddingRoom] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;
  const isAdmin = session.role === "admin";

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    const days = Number(decayDays);
    if (!name.trim() || days < 1) return;
    createRoom.mutate({ name: name.trim(), decay_days: days });
    setName("");
    setDecayDays("7");
  };

  const addTask = (roomId: string) => {
    if (!taskTitle.trim()) return;
    createInstance.mutate(
      { title: taskTitle.trim(), room_id: roomId },
      {
        onSuccess: () => {
          setAddingRoom(null);
          setTaskTitle("");
        },
      },
    );
  };

  return (
    <section aria-labelledby="rooms-heading" className="space-y-8">
      <h1 id="rooms-heading" className="font-display text-2xl">
        <Trans id="rooms.section" />
      </h1>

      {heatmap.isLoading ? (
        <LoadingState />
      ) : heatmap.isError ? (
        <ErrorState />
      ) : heatmap.data && heatmap.data.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {heatmap.data.map((room) => (
            <li
              key={room.room_id}
              className={`flex flex-col gap-2 rounded-lg border p-4 ${
                STATUS_CLASS[room.status] ?? ""
              }`}
            >
              <div className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-2">
                  <span
                    className={`inline-block h-3 w-3 rounded-full ${STATUS_DOT[room.status] ?? ""}`}
                    aria-hidden
                  />
                  <span className="font-display text-lg text-tinte dark:text-kalk">
                    {room.icon ? `${room.icon} ` : ""}
                    {room.name}
                  </span>
                </span>
                {/* Tinted card backgrounds shave --stein-text below AA (~4.3:1 on the rosé tint),
                    so the secondary text goes a notch darker here; dark keeps the token. */}
                <span className="flex items-center gap-3 text-sm text-tinte/75 dark:text-stein-text">
                  <span>
                    {room.last_done ? (
                      new Date(room.last_done).toLocaleDateString()
                    ) : (
                      <Trans id="rooms.never" />
                    )}
                  </span>
                  {isAdmin ? (
                    <button
                      type="button"
                      onClick={() => deleteRoom.mutate(room.room_id)}
                      className="text-bernstein-text dark:text-bernstein hover:underline"
                    >
                      <Trans id="rooms.delete" />
                    </button>
                  ) : null}
                </span>
              </div>
              {/* S-13: the heatmap is an action surface — add a task straight to a room. */}
              {addingRoom === room.room_id ? (
                <div className="flex items-center gap-2">
                  <input
                    value={taskTitle}
                    onChange={(e) => setTaskTitle(e.target.value)}
                    placeholder={i18n._("rooms.taskTitle")}
                    className="flex-1 rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-1.5 text-sm text-tinte dark:text-kalk"
                  />
                  <button
                    type="button"
                    onClick={() => addTask(room.room_id)}
                    disabled={createInstance.isPending || !taskTitle.trim()}
                    className="text-sm text-laurus dark:text-laurus-dark hover:underline"
                  >
                    <Trans id="rooms.taskAdd" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAddingRoom(null);
                      setTaskTitle("");
                    }}
                    className="text-sm text-stein-text hover:underline"
                  >
                    <Trans id="rooms.taskCancel" />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setAddingRoom(room.room_id);
                    setTaskTitle("");
                  }}
                  className="self-start text-sm text-laurus dark:text-laurus-dark hover:underline"
                >
                  <Trans id="rooms.addTask" />
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState>
          <Trans id="rooms.empty" />
        </EmptyState>
      )}

      {isAdmin ? (
        <section aria-labelledby="new-room-heading" className="space-y-3">
          <h2 id="new-room-heading" className="font-display text-lg">
            <Trans id="rooms.add" />
          </h2>
          <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
            <Field
              id="room-name"
              label={<Trans id="rooms.name" />}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Field
              id="room-decay"
              type="number"
              min={1}
              label={<Trans id="rooms.decayDays" />}
              value={decayDays}
              onChange={(e) => setDecayDays(e.target.value)}
              className="w-28"
            />
            <Button type="submit" disabled={createRoom.isPending || !name.trim()}>
              <Trans id="rooms.add" />
            </Button>
          </form>
        </section>
      ) : null}
    </section>
  );
}
