import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import type { LinkResponse } from "../api/types.gen";
import { toProblem } from "../auth/session";

export const LINKS_QUERY_KEY = ["links"] as const;

async function fetchLinks(objectType: string, objectId: string): Promise<LinkResponse[]> {
  const { data, error, response } = await client.get({
    url: "/v1/links",
    query: { object_type: objectType, object_id: objectId },
  });
  if (error) throw toProblem(error, response?.status);
  return (data ?? []) as LinkResponse[];
}

async function createLink(vars: {
  aType: string;
  aId: string;
  bType: string;
  bId: string;
  relation?: string;
}): Promise<LinkResponse> {
  const { data, error, response } = await client.post({
    url: "/v1/links",
    body: {
      a_type: vars.aType,
      a_id: vars.aId,
      b_type: vars.bType,
      b_id: vars.bId,
      ...(vars.relation ? { relation: vars.relation } : {}),
    },
  });
  if (error) throw toProblem(error, response?.status);
  return data as LinkResponse;
}

async function deleteLink(id: string): Promise<void> {
  const { error, response } = await client.delete({ url: `/v1/links/${id}` });
  if (error) throw toProblem(error, response?.status);
}

export function useLinks(objectType: string, objectId: string | null) {
  return useQuery({
    queryKey: [...LINKS_QUERY_KEY, objectType, objectId],
    queryFn: () => fetchLinks(objectType, objectId as string),
    enabled: objectId !== null,
  });
}

export function useCreateLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createLink,
    onSuccess: () => qc.invalidateQueries({ queryKey: LINKS_QUERY_KEY }),
  });
}

export function useDeleteLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteLink,
    onSuccess: () => qc.invalidateQueries({ queryKey: LINKS_QUERY_KEY }),
  });
}

// The endpoint of a link that is NOT the object we're viewing (links are direction-independent).
export function otherEndpoint(
  link: LinkResponse,
  objectType: string,
  objectId: string,
): { type: string; id: string } {
  const isSrc = link.src_type === objectType && link.src_id === objectId;
  return isSrc
    ? { type: link.dst_type, id: link.dst_id }
    : { type: link.src_type, id: link.src_id };
}
