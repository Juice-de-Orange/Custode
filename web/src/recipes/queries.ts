import { formDataBodySerializer } from "@hey-api/client-fetch";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type {
  NutritionOut,
  RecipeCreate,
  RecipeImportResponse,
  RecipeResponse,
  RecipeSummary,
  RecipeUpdate,
} from "../api/types.gen";
import { toProblem } from "../auth/session";

// A recipe plus its ETag (the row version), so a PATCH can send If-Match for optimistic concurrency
// (ADR-0029); a 412 means someone else changed it first.
export type RecipeWithEtag = RecipeResponse & { etag: string };

function withEtag(data: unknown, response: Response | undefined): RecipeWithEtag {
  return { ...(data as RecipeResponse), etag: response?.headers.get("etag") ?? "" };
}

async function fetchRecipes(): Promise<RecipeSummary[]> {
  const { data, error, response } = await client.get({ url: "/v1/recipes" });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as RecipeSummary[];
}

async function fetchRecipe(id: string): Promise<RecipeWithEtag> {
  const { data, error, response } = await client.get({ url: `/v1/recipes/${id}` });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function postRecipe(body: RecipeCreate): Promise<RecipeWithEtag> {
  const { data, error, response } = await client.post({ url: "/v1/recipes", body });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function patchRecipe(vars: {
  id: string;
  update: RecipeUpdate;
  etag: string;
}): Promise<RecipeWithEtag> {
  const { data, error, response } = await client.patch({
    url: `/v1/recipes/${vars.id}`,
    body: vars.update,
    headers: { "If-Match": vars.etag },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function deleteRecipe(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/recipes/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export async function putPhoto(vars: { id: string; file: File }): Promise<RecipeWithEtag> {
  // Multipart via the client's own serializer; `Content-Type: null` drops the JSON default so the
  // runtime sets the multipart boundary (see guides/queries.ts, BUGLOG 2026-10-03).
  const { data, error, response } = await client.put({
    url: `/v1/recipes/${vars.id}/photo`,
    ...formDataBodySerializer,
    body: { file: vars.file },
    headers: { "Content-Type": null },
  });
  if (error) throw toProblem(error, response?.status);
  return withEtag(data, response);
}

async function deletePhoto(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/recipes/${id}/photo` });
  if (error) throw toProblem(error, response?.status);
}

async function postImport(url: string): Promise<RecipeImportResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/recipes/import",
    body: { url },
  });
  if (error) throw toProblem(error, response?.status);
  return data as RecipeImportResponse;
}

export const RECIPES_QUERY_KEY = ["recipes"] as const;
export const recipeKey = (id: string) => ["recipes", id] as const;

export function useRecipes() {
  return useQuery({ queryKey: RECIPES_QUERY_KEY, queryFn: fetchRecipes });
}

export function useRecipe(id: string) {
  return useQuery({ queryKey: recipeKey(id), queryFn: () => fetchRecipe(id) });
}

export function useCreateRecipe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postRecipe,
    onSuccess: () => qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY }),
  });
}

export function useUpdateRecipe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchRecipe,
    onSuccess: (data) => {
      qc.setQueryData(recipeKey(data.id), data); // keep the fresh ETag for the next save
      qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY });
    },
  });
}

export function useDeleteRecipe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteRecipe,
    onSuccess: () => qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY }),
  });
}

export function useUploadPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: putPhoto,
    onSuccess: (data) => {
      qc.setQueryData(recipeKey(data.id), data);
      qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY });
    },
  });
}

export function useDeletePhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deletePhoto,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: recipeKey(id) });
      qc.invalidateQueries({ queryKey: RECIPES_QUERY_KEY });
    },
  });
}

// Extract a draft from a URL (server fetches SSRF-guarded). Not a cache write — the draft is
// reviewed and then saved via useCreateRecipe.
export function useImportRecipe() {
  return useMutation({ mutationFn: postImport });
}

async function fetchNutrition(id: string): Promise<NutritionOut> {
  const { data, error, response } = await client.get({ url: `/v1/recipes/${id}/nutrition` });
  if (error) throw toProblem(error, response?.status);
  return data as NutritionOut;
}

export function useRecipeNutrition(id: string) {
  return useQuery({ queryKey: ["recipes", id, "nutrition"], queryFn: () => fetchNutrition(id) });
}
