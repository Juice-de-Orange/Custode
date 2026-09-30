import { useGuides } from "../guides/queries";
import { useNotes } from "../notes/queries";
import { useRecipes } from "../recipes/queries";
import { useTaskInstances } from "../tasks/queries";

// The object types that can be linked (KONZEPT §5.12). Kept in sync with the backend's discriminator.
export const LINKABLE_TYPES = ["recipe", "task", "note", "guide"] as const;
export type LinkableType = (typeof LINKABLE_TYPES)[number];

export type ObjectOption = { id: string; label: string };

// Candidate targets of one type, excluding the object itself (a self-link is a 422 server-side).
export function pickCandidates(
  byType: Record<string, ObjectOption[]>,
  otherType: string,
  selfType: string,
  selfId: string,
): ObjectOption[] {
  return (byType[otherType] ?? []).filter(
    (o) => !(otherType === selfType && o.id === selfId),
  );
}

// The label of one object, or null when it is unknown (e.g. a since-deleted link target).
export function resolveLabel(
  byType: Record<string, ObjectOption[]>,
  type: string,
  id: string,
): string | null {
  return byType[type]?.find((o) => o.id === id)?.label ?? null;
}

// Resolve human labels for the linkable object types so links are picked + shown by name, not raw
// UUIDs. Each type already has a household-scoped list endpoint; React Query dedupes/caches them, so
// embedding this in every LinksPanel is cheap. A label missing here (e.g. a since-deleted target)
// falls back to the short id at the call site.
export function useObjectOptions() {
  const recipes = useRecipes();
  const notes = useNotes();
  const guides = useGuides("");
  const tasks = useTaskInstances();

  const byType: Record<string, ObjectOption[]> = {
    recipe: (recipes.data ?? []).map((r) => ({ id: r.id, label: r.title })),
    note: (notes.data ?? []).map((n) => ({ id: n.id, label: n.title })),
    guide: (guides.data ?? []).map((g) => ({ id: g.id, label: g.title })),
    task: (tasks.data ?? []).map((t) => ({ id: t.id, label: t.title })),
  };

  const labelOf = (type: string, id: string): string | null =>
    resolveLabel(byType, type, id);

  return { byType, labelOf };
}
