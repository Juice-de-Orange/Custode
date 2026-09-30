import { describe, expect, it } from "vitest";

import { pickCandidates, resolveLabel, type ObjectOption } from "../links/objects";

const byType: Record<string, ObjectOption[]> = {
  recipe: [
    { id: "r1", label: "Lasagne" },
    { id: "r2", label: "Pesto" },
  ],
  note: [{ id: "n1", label: "Einkauf" }],
};

describe("pickCandidates", () => {
  it("lists all objects of a type when none is the current object", () => {
    expect(pickCandidates(byType, "recipe", "note", "n1")).toHaveLength(2);
  });

  it("excludes the object itself (a self-link is rejected server-side)", () => {
    const out = pickCandidates(byType, "recipe", "recipe", "r1");
    expect(out.map((o) => o.id)).toEqual(["r2"]);
  });

  it("returns an empty list for an unknown / unloaded type", () => {
    expect(pickCandidates(byType, "guide", "recipe", "r1")).toEqual([]);
  });
});

describe("resolveLabel", () => {
  it("resolves a known object's label", () => {
    expect(resolveLabel(byType, "recipe", "r2")).toBe("Pesto");
  });

  it("returns null for an unknown id (e.g. a since-deleted target)", () => {
    expect(resolveLabel(byType, "recipe", "gone")).toBeNull();
    expect(resolveLabel(byType, "task", "x")).toBeNull();
  });
});
