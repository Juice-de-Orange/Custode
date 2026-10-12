import { Trans } from "@lingui/react";
import { useEffect, useState } from "react";

import { onDemoDisabled, useDemo } from "../lib/demo";

// Shown on every page of a public demo instance (docs/demo.md), signed in or not. It also tells
// search engines to stay away (the server sends X-Robots-Tag too) and explains a refused action.
export function DemoBanner() {
  const demo = useDemo();
  const [refused, setRefused] = useState(false);

  useEffect(() => onDemoDisabled(() => setRefused(true)), []);

  useEffect(() => {
    if (!demo) return;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, [demo]);

  if (!demo) return null;
  return (
    <div
      role="status"
      className="bg-bernstein/15 px-4 py-2 text-sm text-tinte md:px-6 dark:text-kalk"
    >
      <Trans id={demo.resetting ? "demo.banner.resetting" : "demo.banner"} />
      {refused ? (
        <>
          {" "}
          <strong>
            <Trans id="demo.refused" />
          </strong>
        </>
      ) : null}
    </div>
  );
}
