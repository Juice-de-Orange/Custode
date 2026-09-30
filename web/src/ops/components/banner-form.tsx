import { Trans } from "@lingui/react";
import { useState } from "react";

import { Field } from "../../components/field";
import type { BannerCreate } from "../../api/types.gen";

// ``level`` is an inline literal union on BannerCreate (no named export); derive it here.
type BannerLevel = NonNullable<BannerCreate["level"]>;

type Props = { onSubmit: (values: BannerCreate) => void; pending: boolean };

// Pure, controlled banner-create form (message + level). Dates are optional on the API and
// omitted here for a first cut — a banner created without a window is active immediately.
export function BannerForm({ onSubmit, pending }: Props) {
  const [message, setMessage] = useState("");
  const [level, setLevel] = useState<BannerLevel>("info");

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!message.trim()) return;
        onSubmit({ message: message.trim(), level });
        setMessage("");
      }}
    >
      <Field
        id="banner-message"
        label={<Trans id="ops.banners.message" />}
        required
        maxLength={500}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />
      <div className="space-y-1">
        <label htmlFor="banner-level" className="block text-sm font-medium text-tinte dark:text-kalk">
          <Trans id="ops.banners.level" />
        </label>
        <select
          id="banner-level"
          value={level}
          onChange={(e) => setLevel(e.target.value as BannerLevel)}
          className="block w-full rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
        >
          <option value="info">{"info"}</option>
          <option value="warning">{"warning"}</option>
        </select>
      </div>
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-laurus px-4 py-2 text-kalk hover:bg-laurus/90 focus:outline-none focus:ring-2 focus:ring-laurus/40 disabled:opacity-60"
      >
        <Trans id="ops.banners.create" />
      </button>
    </form>
  );
}
