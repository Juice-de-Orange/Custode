import { Trans, useLingui } from "@lingui/react";
import { useQuery } from "@tanstack/react-query";

import { ErrorState, LoadingState } from "../components/states";
import { Markdown } from "../lib/markdown";

// Legal text pages (imprint, privacy policy). Public — readable without a session, since both
// must be reachable by anyone. The texts belong to whoever runs the instance, so they are not in
// the code: the operator drops Markdown files into the `legal/` folder that the web container
// serves under /legal/ (docs/operations.md, "Legal pages"). A language-specific file
// (`imprint.en.md`) wins over the generic one (`imprint.md`). Without a file the page says
// plainly that the operator has not provided one — it never shows a placeholder text that
// looks like a real imprint.

export type LegalDoc = "imprint" | "privacy";

/** Fetch `/legal/<doc>.<locale>.md`, then `/legal/<doc>.md`. `null` = the operator has not
 *  provided the document. A 404 counts as "not provided", and so does an HTML answer: an SPA
 *  fallback (the Vite dev server, a proxy without the /legal/ block) serves index.html for
 *  unknown paths with 200. Network failures throw, so they show as an error, not as "missing". */
export async function fetchLegalDoc(doc: LegalDoc, locale: string): Promise<string | null> {
  for (const name of [`${doc}.${locale}.md`, `${doc}.md`]) {
    const res = await fetch(`/legal/${name}`, { headers: { Accept: "text/markdown, text/plain" } });
    const type = res.headers.get("content-type") ?? "";
    if (res.ok && !type.includes("text/html")) {
      const text = await res.text();
      if (text.trim()) return text;
    }
  }
  return null;
}

function LegalPage({ doc, titleId, missingId }: { doc: LegalDoc; titleId: string; missingId: string }) {
  const { i18n } = useLingui();
  const locale = i18n.locale;
  const text = useQuery({
    queryKey: ["legal", doc, locale],
    queryFn: () => fetchLegalDoc(doc, locale),
    staleTime: 5 * 60_000,
  });
  return (
    <article className="prose-sm mx-auto max-w-prose space-y-4">
      <h1 className="font-display text-2xl">
        <Trans id={titleId} />
      </h1>
      {text.isLoading ? (
        <LoadingState />
      ) : text.isError ? (
        <ErrorState />
      ) : text.data ? (
        <Markdown source={text.data} />
      ) : (
        <p className="rounded-md border border-bernstein/40 bg-bernstein/5 px-3 py-2 text-sm text-stein-text">
          <Trans id={missingId} />
        </p>
      )}
    </article>
  );
}

export function PrivacyPage() {
  return <LegalPage doc="privacy" titleId="legal.privacy.title" missingId="legal.privacy.missing" />;
}

export function ImprintPage() {
  return <LegalPage doc="imprint" titleId="legal.imprint.title" missingId="legal.imprint.missing" />;
}
