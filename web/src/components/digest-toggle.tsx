import { Trans } from "@lingui/react";

import { useDigestSetting, useSetDigestSetting } from "../settings/queries";

// Admin toggle for the household's weekly digest (P8-S7b). Self-contained so it can drop into the
// account page's admin section without entangling other settings.
export function DigestToggle({ isAdmin }: { isAdmin: boolean }) {
  const setting = useDigestSetting(isAdmin);
  const update = useSetDigestSetting();
  if (!isAdmin) return null;
  const enabled = setting.data?.enabled ?? true;
  return (
    <div className="rounded-md border border-stein/30 px-3 py-2">
      <label className="flex items-center gap-2 text-sm text-tinte dark:text-kalk">
        <input
          type="checkbox"
          checked={enabled}
          disabled={setting.isLoading || update.isPending}
          onChange={(e) => update.mutate(e.target.checked)}
        />
        <Trans id="digest.toggle" />
      </label>
      <p className="mt-1 text-xs text-stein-text">
        <Trans id="digest.toggle.hint" />
      </p>
    </div>
  );
}
