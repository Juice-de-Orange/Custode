// Data export (Art. 15/20). Lives on /profile, because the right belongs to the person, not to a
// role — a child may run it too. The household export sits next to it rather than in the household
// settings: it is the same act by the same person, only wider, and an admin should not have to
// look for their own subject rights in two places.
//
// Self-contained (own hook, one `isAdmin` prop) like WearablesSection. The section states plainly
// what the archive holds AND what it deliberately withholds — an export that only advertises
// completeness claims something it does not deliver (the archive's own manifest.json says the same
// in machine-readable form).

import { Trans } from "@lingui/react";
import { FileArchive, Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "../components/button";
import { EmptyState } from "../components/states";
import { i18n } from "../i18n";
import { BRAND_NAME } from "../lib/brand";
import { exportProblemMessage, type MessageRef } from "./errors";
import { type ExportScope, useExportDownload } from "./queries";

export function ExportSection({ isAdmin }: { isAdmin: boolean }) {
  const download = useExportDownload();
  const [failure, setFailure] = useState<MessageRef | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // Which of the two buttons is busy. Both are disabled while either runs: building an archive is
  // the most expensive thing a member can ask the server for, and two at once is never intended.
  const running: ExportScope | null = download.isPending ? (download.variables ?? null) : null;

  function start(scope: ExportScope) {
    setFailure(null);
    setDone(null);
    download.mutate(scope, {
      onSuccess: (filename) => setDone(filename),
      onError: (err) => setFailure(exportProblemMessage(err)),
    });
  }

  return (
    <section aria-labelledby="export-heading" className="space-y-3">
      <h2 id="export-heading" className="font-display text-lg">
        <Trans id="export.title" />
      </h2>
      <p className="text-sm text-stein-text">
        <Trans id="export.intro" values={{ brand: BRAND_NAME }} />
      </p>

      <div className="space-y-2 rounded-lg border border-stein/30 p-4">
        <h3 className="text-sm font-medium">
          <Trans id="export.contains.title" />
        </h3>
        <p className="text-sm text-stein-text">
          <Trans id="export.contains.body" />
        </p>
        <h3 className="pt-1 text-sm font-medium">
          <Trans id="export.missing.title" />
        </h3>
        <p className="text-sm text-stein-text">
          <Trans id="export.missing.body" />
        </p>
        <p className="text-xs text-stein-text">
          <Trans id="export.manifest" />
        </p>
      </div>

      {/* The Trio. All three are announced: the only visible result of a finished export is a file
          appearing in the browser's download shelf, which a screen-reader user cannot see. */}
      {running ? (
        <p
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 text-sm text-stein-text"
        >
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {/* Not the generic LoadingState: this waits on the server building an archive, and
              saying so is the difference between patience and a suspected hang. */}
          <Trans id="export.preparing" />
        </p>
      ) : done ? (
        <p role="status" aria-live="polite" className="text-sm text-stein-text">
          <Trans id="export.done" values={{ file: done }} />
        </p>
      ) : (
        <EmptyState icon={<FileArchive className="size-7" strokeWidth={1.5} />}>
          <Trans id="export.empty" />
        </EmptyState>
      )}

      {failure && (
        <div role="alert" className="space-y-1 text-sm text-rost">
          <p>
            <Trans id={failure.id} />
          </p>
          {failure.reference && (
            <p className="font-mono text-xs text-stein-text">{failure.reference}</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={download.isPending} onClick={() => start("me")}>
          {running === "me" ? i18n._("export.pending") : i18n._("export.me")}
        </Button>
        {isAdmin && (
          <Button
            type="button"
            variant="secondary"
            disabled={download.isPending}
            onClick={() => start("household")}
          >
            {running === "household" ? i18n._("export.pending") : i18n._("export.household")}
          </Button>
        )}
      </div>
      <p className="text-xs text-stein-text">
        <Trans id="export.meHint" />
      </p>
      {isAdmin && (
        <p className="text-xs text-stein-text">
          <Trans id="export.householdHint" />
        </p>
      )}
    </section>
  );
}
