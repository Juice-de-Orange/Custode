import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  CookTaskResult,
  GenerateResult,
  PrepTaskResult,
  SlotSet,
  WeekNutrition,
  WeekResponse,
} from "../api/types.gen";
import { toProblem } from "../auth/session";
import { RECIPES_QUERY_KEY } from "../recipes/queries";
import { SHOPPING_QUERY_KEY } from "../shopping/queries";
import { TASKS_QUERY_KEY } from "../tasks/queries";

async function fetchWeek(weekStart: string): Promise<WeekResponse> {
  const { data, error, response } = await client.get({
    url: "/v1/mealplan",
    query: { week_start: weekStart },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

async function putSlot(vars: { weekStart: string; body: SlotSet }): Promise<WeekResponse> {
  const { data, error, response } = await client.put({
    url: "/v1/mealplan/slot",
    query: { week_start: vars.weekStart },
    body: vars.body,
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

async function deleteSlot(vars: {
  weekStart: string;
  dayOfWeek: number;
  slot: string;
}): Promise<WeekResponse> {
  const { data, error, response } = await client.delete({
    url: "/v1/mealplan/slot",
    query: { week_start: vars.weekStart, day_of_week: vars.dayOfWeek, slot: vars.slot },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

export const MEALPLAN_QUERY_KEY = ["mealplan"] as const;

export function useWeek(weekStart: string) {
  return useQuery({
    queryKey: [...MEALPLAN_QUERY_KEY, weekStart],
    queryFn: () => fetchWeek(weekStart),
  });
}

async function fetchWeekNutrition(
  weekStart: string,
  targetKcal?: number,
): Promise<WeekNutrition> {
  const { data, error, response } = await client.get({
    url: "/v1/mealplan/nutrition",
    query: {
      week_start: weekStart,
      ...(targetKcal !== undefined ? { target_kcal: targetKcal } : {}),
    },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekNutrition;
}

export function useWeekNutrition(weekStart: string, targetKcal?: number) {
  return useQuery({
    queryKey: [...MEALPLAN_QUERY_KEY, weekStart, "nutrition", targetKcal ?? null],
    queryFn: () => fetchWeekNutrition(weekStart, targetKcal),
  });
}

function useMealplanMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: MEALPLAN_QUERY_KEY }),
  });
}

export function useSetSlot() {
  return useMealplanMutation(putSlot);
}

export function useClearSlot() {
  return useMealplanMutation(deleteSlot);
}

async function suggestSlot(vars: {
  weekStart: string;
  dayOfWeek: number;
  slot: string;
  lockoutDays?: number;
}): Promise<WeekResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/suggest",
    query: {
      week_start: vars.weekStart,
      day_of_week: vars.dayOfWeek,
      slot: vars.slot,
      ...(vars.lockoutDays !== undefined ? { lockout_days: vars.lockoutDays } : {}),
    },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

export function useSuggestSlot() {
  return useMealplanMutation(suggestSlot);
}

async function suggestWeek(vars: {
  weekStart: string;
  slot: string;
  lockoutDays?: number;
  targetKcal?: number;
  excludeTags?: string[];
}): Promise<WeekResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/suggest-week",
    query: {
      week_start: vars.weekStart,
      slot: vars.slot,
      ...(vars.lockoutDays !== undefined ? { lockout_days: vars.lockoutDays } : {}),
      ...(vars.targetKcal !== undefined ? { target_kcal: vars.targetKcal } : {}),
      ...(vars.excludeTags && vars.excludeTags.length > 0
        ? { exclude_tag: vars.excludeTags }
        : {}),
    },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

export function useSuggestWeek() {
  return useMealplanMutation(suggestWeek);
}

async function copyWeek(vars: { weekStart: string; sourceWeek?: string }): Promise<WeekResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/copy",
    query: {
      week_start: vars.weekStart,
      ...(vars.sourceWeek !== undefined ? { source_week: vars.sourceWeek } : {}),
    },
  });
  if (error) throw toProblem(error, response?.status);
  return data as WeekResponse;
}

export function useCopyWeek() {
  return useMealplanMutation(copyWeek);
}

async function createCookTask(vars: {
  weekStart: string;
  dayOfWeek: number;
  slot: string;
}): Promise<CookTaskResult> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/slot/cook-task",
    query: { week_start: vars.weekStart, day_of_week: vars.dayOfWeek, slot: vars.slot },
  });
  if (error) throw toProblem(error, response?.status);
  return data as CookTaskResult;
}

export function useCreateCookTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCookTask,
    // The cooking task lands in the tasks module -> refresh task views.
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}

async function createPrepTask(vars: {
  weekStart: string;
  dayOfWeek: number;
  slot: string;
}): Promise<PrepTaskResult> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/slot/prep-task",
    query: { week_start: vars.weekStart, day_of_week: vars.dayOfWeek, slot: vars.slot },
  });
  if (error) throw toProblem(error, response?.status);
  return data as PrepTaskResult;
}

export function useCreatePrepTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createPrepTask,
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_QUERY_KEY }),
  });
}

async function generateShopping(weekStart: string): Promise<GenerateResult> {
  const { data, error, response } = await client.post({
    url: "/v1/mealplan/to-shopping",
    query: { week_start: weekStart },
  });
  if (error) throw toProblem(error, response?.status);
  return data as GenerateResult;
}

export function useGenerateShopping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: generateShopping,
    // The generated items land in the shopping list -> refresh it.
    onSuccess: () => qc.invalidateQueries({ queryKey: SHOPPING_QUERY_KEY }),
  });
}

async function markCooked(vars: {
  weekStart: string;
  dayOfWeek: number;
  slot: string;
}): Promise<void> {
  const { error, response } = await client.post({
    url: "/v1/mealplan/slot/cooked",
    query: { week_start: vars.weekStart, day_of_week: vars.dayOfWeek, slot: vars.slot },
  });
  if (error) throw toProblem(error, response?.status);
}

export function useMarkCooked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markCooked,
    // Cooking bumps the recipe's "last cooked" history -> refresh the recipe views.
    onSuccess: () => qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY }),
  });
}
