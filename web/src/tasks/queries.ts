import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  RoomCreate,
  RoomHeatmapEntry,
  RoomResponse,
  TaskInstanceCreate,
  TaskInstanceResponse,
  TaskTemplateCreate,
  TaskTemplateResponse,
  TaskTemplateSummary,
} from "../api/types.gen";
import { toProblem } from "../auth/session";
import type { LocalizedPreset } from "../lib/presets";

// An instance plus its ETag (the row version), so completing can send If-Match for optimistic
// concurrency (ADR-0034); a 412 means it changed first, a 409 means it is no longer open.
export type InstanceWithEtag = TaskInstanceResponse & { etag: string };

function withEtag(data: unknown, response: Response | undefined): InstanceWithEtag {
  return { ...(data as TaskInstanceResponse), etag: response?.headers.get("etag") ?? "" };
}

async function fetchTemplates(): Promise<TaskTemplateSummary[]> {
  const { data, error, response } = await client.get({ url: "/v1/tasks/templates" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as TaskTemplateSummary[];
}

async function postTemplate(body: TaskTemplateCreate): Promise<TaskTemplateResponse> {
  const { data, error, response } = await client.post({ url: "/v1/tasks/templates", body });
  if (error) throw toProblem(error, response?.status);
  return data as TaskTemplateResponse;
}

async function deleteTemplate(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/tasks/templates/${id}` });
  if (error) throw toProblem(error, response?.status);
}

async function fetchInstances(): Promise<InstanceWithEtag[]> {
  const { data, error, response } = await client.get({ url: "/v1/tasks/instances" });
  if (error) throw toProblem(error, response?.status);
  // The list ETag is per-row (version); carry each so the complete action can send If-Match.
  return ((data ?? []) as TaskInstanceResponse[]).map((i) => ({ ...i, etag: String(i.version) }));
}

async function postInstance(body: TaskInstanceCreate): Promise<InstanceWithEtag> {
  const { data, error, response } = await client.post({ url: "/v1/tasks/instances", body });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function completeInstance(vars: { id: string; etag: string }): Promise<InstanceWithEtag> {
  const { data, error, response } = await client.post({
    url: `/v1/tasks/instances/${vars.id}/complete`,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

export const TASKS_QUERY_KEY = ["tasks"] as const;
const TEMPLATES_QUERY_KEY = ["tasks", "templates"] as const;
const INSTANCES_QUERY_KEY = ["tasks", "instances"] as const;

export function useTaskTemplates() {
  return useQuery({ queryKey: TEMPLATES_QUERY_KEY, queryFn: fetchTemplates });
}

export function useTaskInstances() {
  return useQuery({ queryKey: INSTANCES_QUERY_KEY, queryFn: fetchInstances });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postTemplate,
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY }),
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteTemplate,
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY }),
  });
}

export function useCreateInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postInstance,
    onSuccess: () => qc.invalidateQueries({ queryKey: INSTANCES_QUERY_KEY }),
  });
}

export function useCompleteInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: completeInstance,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: INSTANCES_QUERY_KEY });
      // completing credits the points ledger (ADR-0035) -> refresh the balance + ledger views
      qc.invalidateQueries({ queryKey: ["economy"] });
      // a completion changes its room's freshness -> refresh the heatmap (S-13)
      qc.invalidateQueries({ queryKey: HEATMAP_QUERY_KEY });
    },
  });
}

// --- Rooms + heatmap (P4-S6) -------------------------------------------------

async function fetchHeatmap(): Promise<RoomHeatmapEntry[]> {
  const { data, error, response } = await client.get({ url: "/v1/tasks/heatmap" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as RoomHeatmapEntry[];
}

async function fetchRooms(): Promise<RoomResponse[]> {
  const { data, error, response } = await client.get({ url: "/v1/tasks/rooms" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as RoomResponse[];
}

async function postRoom(body: RoomCreate): Promise<RoomResponse> {
  const { data, error, response } = await client.post({ url: "/v1/tasks/rooms", body });
  if (error) throw toProblem(error, response?.status);
  return data as RoomResponse;
}

async function deleteRoom(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/tasks/rooms/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export const HEATMAP_QUERY_KEY = ["tasks", "heatmap"] as const;
export const ROOMS_QUERY_KEY = ["tasks", "rooms"] as const;

export function useHeatmap() {
  return useQuery({ queryKey: HEATMAP_QUERY_KEY, queryFn: fetchHeatmap });
}

export function useRooms() {
  return useQuery({ queryKey: ROOMS_QUERY_KEY, queryFn: fetchRooms });
}

export function useCreateRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postRoom,
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}

export function useDeleteRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteRoom,
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}

// --- Onboarding: apply a curated preset (P8-S2) ------------------------------

// Seed a fresh household from a preset: create its rooms first (so each gets a server id), then the
// task templates pointing at those rooms. One mutation so the UI gets a single pending/error state.
async function applyPreset(preset: LocalizedPreset): Promise<void> {
  const slugToId = new Map<string, string>();
  for (const room of preset.rooms) {
    const created = await postRoom({ name: room.name, icon: room.icon, decay_days: room.decay_days });
    slugToId.set(room.slug, created.id);
  }
  for (const tpl of preset.templates) {
    await postTemplate({
      title: tpl.title,
      points: tpl.points,
      outdoor: tpl.outdoor,
      rotation: tpl.rotation,
      room_id: tpl.room ? (slugToId.get(tpl.room) ?? null) : null,
    });
  }
}

export function useApplyPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: applyPreset,
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}
