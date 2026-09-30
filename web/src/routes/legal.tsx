import { Trans } from "@lingui/react";

import { BRAND_NAME } from "../lib/brand";

// Legal text pages (Roadmap Phase 8: „DSGVO-Texte v1"). Public — readable without a session, since a
// privacy policy and imprint must be reachable by anyone. Content is a structured v1 draft (clearly
// marked); the binding wording is filled in during the legal review before the public launch (Phase 11).
function LegalShell({ titleId, children }: { titleId: string; children: React.ReactNode }) {
  return (
    <article className="prose-sm mx-auto max-w-prose space-y-4">
      <h1 className="font-display text-2xl">
        <Trans id={titleId} />
      </h1>
      <p className="rounded-md border border-bernstein/40 bg-bernstein/5 px-3 py-2 text-sm text-stein-text">
        <Trans id="legal.draftNotice" />
      </p>
      {children}
    </article>
  );
}

function Section({ headingId, bodyId }: { headingId: string; bodyId: string }) {
  return (
    <section className="space-y-1">
      <h2 className="text-base font-semibold text-tinte dark:text-kalk">
        <Trans id={headingId} />
      </h2>
      <p className="text-sm text-stein-text">
        <Trans id={bodyId} />
      </p>
    </section>
  );
}

export function PrivacyPage() {
  return (
    <LegalShell titleId="legal.privacy.title">
      <Section headingId="legal.privacy.controller.h" bodyId="legal.privacy.controller.b" />
      <Section headingId="legal.privacy.data.h" bodyId="legal.privacy.data.b" />
      <Section headingId="legal.privacy.purposes.h" bodyId="legal.privacy.purposes.b" />
      <Section headingId="legal.privacy.legalBasis.h" bodyId="legal.privacy.legalBasis.b" />
      <Section headingId="legal.privacy.retention.h" bodyId="legal.privacy.retention.b" />
      <Section headingId="legal.privacy.rights.h" bodyId="legal.privacy.rights.b" />
      <Section headingId="legal.privacy.contact.h" bodyId="legal.privacy.contact.b" />
    </LegalShell>
  );
}

export function ImprintPage() {
  return (
    <LegalShell titleId="legal.imprint.title">
      <Section headingId="legal.imprint.provider.h" bodyId="legal.imprint.provider.b" />
      <Section headingId="legal.imprint.contact.h" bodyId="legal.imprint.contact.b" />
      <p className="text-sm text-stein-text">
        <Trans id="legal.imprint.brandNote" values={{ brand: BRAND_NAME }} />
      </p>
    </LegalShell>
  );
}
