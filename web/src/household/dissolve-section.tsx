// „Haushalt auflösen" (Art. 17, ADR-0085). Auf /account unterhalb der Mitgliederliste, nur für
// Admins — dort wird der Haushalt verwaltet, und dies ist die letzte Verwaltungshandlung.
//
// Drei Entscheidungen, jede gegen eine konkrete Gefahr:
//
// 1. **Der Haushaltsname wird abgetippt**, kein `window.confirm`. Das ist die schärfste
//    irreversible Aktion der Anwendung; ein Wert, den ein Angreifer nicht kennt, macht sie gegen
//    Clickjacking-Restrisiken unbrauchbar — und zwingt zu einem Moment Innehalten.
// 2. **Die Vorschau steht VOR dem Knopf**, nicht als Fehler danach. Wie viele Menschen es trifft
//    und wie viele Kinder-Konten mit enden, gehört zur Entscheidung, nicht zur Quittung.
// 3. **Die Folgen sind ausgeschrieben — auch die, die überrascht.** Kinder-Konten enden. Es gibt
//    kein Zurück, auch nicht innerhalb der 30 Tage: die Frist ist eine Purge-Verzögerung, kein
//    Undo (KONZEPT §5.1). Der Export geht jetzt oder nie.

import { Trans, useLingui } from "@lingui/react";
import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "../components/button";
import { ErrorState, LoadingState } from "../components/states";
import { memberProblemMessage, type MessageRef } from "./errors";
import { useDissolveHousehold, useDissolvePreview } from "./queries";

export function DissolveSection({ onDissolved }: { onDissolved: () => void }) {
  const { i18n } = useLingui();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [failure, setFailure] = useState<MessageRef | null>(null);
  const preview = useDissolvePreview(open);
  const dissolve = useDissolveHousehold();

  const expected = preview.data?.household_name ?? "";
  const matches = typed.trim() !== "" && typed.trim() === expected.trim();

  return (
    <section aria-labelledby="dissolve-heading" className="space-y-3 border-t border-rost/30 pt-6">
      <h3 id="dissolve-heading" className="font-medium text-rost">
        <Trans id="dissolve.title" />
      </h3>
      <p className="text-sm text-stein-text">
        <Trans id="dissolve.intro" />
      </p>

      {!open ? (
        <Button type="button" variant="secondary" size="sm" onClick={() => setOpen(true)}>
          <Trans id="dissolve.open" />
        </Button>
      ) : preview.isError ? (
        <ErrorState />
      ) : /* `!isSuccess`, nicht `!isLoading` — eine offline pausierte Abfrage ist weder ladend noch
            geladen, und der Name, gegen den bestätigt wird, käme sonst als leerer String. */
      !preview.isSuccess ? (
        <LoadingState />
      ) : (
        <div className="space-y-3">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>
              {i18n._("dissolve.consequence.members", { count: preview.data.member_count })}
            </li>
            {preview.data.child_account_count > 0 ? (
              <li className="font-medium">
                {i18n._("dissolve.consequence.children", {
                  count: preview.data.child_account_count,
                })}
              </li>
            ) : null}
            <li>
              <Trans id="dissolve.consequence.economy" />
            </li>
            <li>
              <Trans id="dissolve.consequence.access" />
            </li>
            <li>
              <Trans id="dissolve.consequence.final" />
            </li>
          </ul>

          <label className="block space-y-1 text-sm">
            <span>{i18n._("dissolve.confirmLabel", { name: expected })}</span>
            <input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              className="w-full rounded-md border border-stein/40 bg-transparent px-2 py-1"
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="danger"
              size="sm"
              disabled={!matches || dissolve.isPending}
              onClick={() => {
                setFailure(null);
                dissolve.mutate(typed.trim(), {
                  onSuccess: onDissolved,
                  onError: (err) => setFailure(memberProblemMessage(err)),
                });
              }}
            >
              {dissolve.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
              <Trans id="dissolve.confirm" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={dissolve.isPending}
              onClick={() => {
                setOpen(false);
                setTyped("");
              }}
            >
              <Trans id="dissolve.cancel" />
            </Button>
          </div>
        </div>
      )}

      {failure ? (
        <p role="alert" className="text-sm text-rost">
          <Trans id={failure.id} />
          {failure.reference ? (
            <span className="ml-1 font-mono text-xs">({failure.reference})</span>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}
