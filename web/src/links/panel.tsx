import { Trans } from "@lingui/react";
import { useState } from "react";

import { Button } from "../components/button";
import { i18n } from "../i18n";
import { LINKABLE_TYPES, pickCandidates, useObjectOptions } from "./objects";
import { otherEndpoint, useCreateLink, useDeleteLink, useLinks } from "./queries";

// A reusable panel of an object's links to other objects (direction-independent). Embed with the
// object's own type + id.
export function LinksPanel({
  objectType,
  objectId,
}: {
  objectType: string;
  objectId: string;
}) {
  const links = useLinks(objectType, objectId);
  const create = useCreateLink();
  const remove = useDeleteLink();
  const { byType, labelOf } = useObjectOptions();
  const [otherType, setOtherType] = useState<string>(LINKABLE_TYPES[0]);
  const [otherId, setOtherId] = useState("");

  // Candidate targets of the chosen type, excluding this object itself (a self-link is a 422).
  const candidates = pickCandidates(byType, otherType, objectType, objectId);

  const submit = () => {
    const id = otherId.trim();
    if (!id) return;
    create.mutate(
      { aType: objectType, aId: objectId, bType: otherType, bId: id },
      { onSuccess: () => setOtherId("") },
    );
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-stein-text">
        <Trans id="links.heading" />
      </h3>
      <ul className="space-y-1">
        {links.data?.map((link) => {
          const other = otherEndpoint(link, objectType, objectId);
          const label = labelOf(other.type, other.id);
          return (
            <li key={link.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-tinte">
                <span className="rounded bg-kalk px-1 text-xs text-stein-text">{other.type}</span>{" "}
                {label !== null ? (
                  <span>{label}</span>
                ) : (
                  <span className="font-mono text-xs">{other.id.slice(0, 8)}</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => remove.mutate(link.id)}
                className="shrink-0 text-xs text-bernstein hover:underline"
              >
                <Trans id="links.remove" />
              </button>
            </li>
          );
        })}
        {(links.data?.length ?? 0) === 0 ? (
          <li className="text-sm text-stein-text">
            <Trans id="links.empty" />
          </li>
        ) : null}
      </ul>
      <div className="flex gap-2">
        <select
          value={otherType}
          onChange={(e) => {
            setOtherType(e.target.value);
            setOtherId("");
          }}
          aria-label={i18n._("links.type")}
          className="rounded border border-stein/40 bg-kalk px-2 py-1 text-sm text-tinte dark:border-stein/25 dark:bg-nacht-2 dark:text-kalk"
        >
          {LINKABLE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={otherId}
          onChange={(e) => setOtherId(e.target.value)}
          aria-label={i18n._("links.pick")}
          disabled={candidates.length === 0}
          className="flex-1 rounded border border-stein/40 bg-kalk px-2 py-1 text-sm text-tinte dark:border-stein/25 dark:bg-nacht-2 dark:text-kalk"
        >
          <option value="">
            {candidates.length === 0 ? i18n._("links.none") : i18n._("links.pick")}
          </option>
          {candidates.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
        <Button onClick={submit} disabled={!otherId.trim() || create.isPending}>
          <Trans id="links.add" />
        </Button>
      </div>
    </div>
  );
}
