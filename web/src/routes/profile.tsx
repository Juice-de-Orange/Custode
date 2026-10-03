import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { DangerZone } from "../account-deletion/danger-zone";
import { ProblemError, useProfile, useSession, useUpdateProfile } from "../auth/session";
import { InstallAppSection } from "../components/install-app";
import { LanguageSection } from "../components/language-section";
import { ProfileForm } from "../components/profile-form";
import { ErrorState, LoadingState } from "../components/states";
import { ExportSection } from "../export/export-section";
import { flagEnabled } from "../lib/flags";
import { WearablesSection } from "../wearables/wearables-section";

// Protected self-service profile editor (KONZEPT §5.1). Loads the profile (+ ETag) and saves with
// If-Match; a 412 conflict surfaces a "changed elsewhere" message and refetches the latest.
export function ProfilePage() {
  const navigate = useNavigate();
  const session = useSession();
  const profile = useProfile();
  const update = useUpdateProfile();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!session.isLoading && session.data === null) navigate({ to: "/login" });
  }, [session.isLoading, session.data, navigate]);

  if (session.isLoading || session.data === null || profile.isLoading) return <LoadingState />;
  if (profile.isError || !profile.data) return <ErrorState />;

  const current = profile.data;
  // The OAuth callback is a server-side redirect back to this page (backend router._back).
  const params = new URLSearchParams(window.location.search);
  const connected = params.get("connected") ?? undefined;
  const callbackError = params.get("error") ?? undefined;
  // Health data is member-private, so this belongs on the personal page, not a household one.
  const showWearables = flagEnabled(session.data?.flags, "wearables");

  return (
    <section aria-labelledby="profile-heading" className="mx-auto max-w-sm space-y-6">
      <h1 id="profile-heading" className="font-display text-2xl">
        <Trans id="profile.title" />
      </h1>
      <ProfileForm
        initial={{
          display_name: current.display_name,
          work_hours: current.work_hours,
          dietary: current.dietary,
        }}
        pending={update.isPending}
        error={error}
        saved={saved}
        onSubmit={(values) => {
          setError(null);
          setSaved(false);
          update.mutate(
            { update: values, etag: current.etag },
            {
              onSuccess: () => setSaved(true),
              onError: (err) => {
                const slug = err instanceof ProblemError ? err.slug : "error";
                if (slug === "precondition_failed") {
                  setError("profile.error.conflict");
                  profile.refetch(); // pull the latest version so a retry uses a fresh ETag
                } else {
                  setError("state.error");
                }
              },
            },
          );
        }}
      />
      {/* Install affordance (ADR-0078): permanent quiet placement — Chromium prompts, iOS gets
          the manual steps, an installed/standalone app sees nothing. */}
      <InstallAppSection />

      <LanguageSection />

      {showWearables && (
        <WearablesSection connected={connected} callbackError={callbackError} />
      )}

      {/* Subject rights (Art. 15/20). The personal copy is for every role; the household copy is
          admin-only and the backend enforces that — this flag only decides whether offering the
          button is honest. Household *settings* live on /account, but a person's own rights
          belong on their own page. */}
      <ExportSection isAdmin={session.data?.role === "admin"} />

      {/* Art. 17, directly below Art. 15/20: the export is what you take with you, this is the
          door out. Placed last and visually separated so it is never a mis-click. */}
      <DangerZone onDeleted={() => navigate({ to: "/login" })} />

      <Link to="/" className="block text-sm text-laurus dark:text-laurus-dark hover:underline">
        <Trans id="security.back" />
      </Link>
    </section>
  );
}
