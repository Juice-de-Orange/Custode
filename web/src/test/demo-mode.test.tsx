import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";

// Public demo mode (docs/demo.md): the server answers /v1/demo only on a demo instance. Every
// page shows the banner there, the sign-in page carries the shared login, sign-up and password
// reset say why they are off, and a refused action (`demo_disabled`) is explained in the banner.
// On a normal instance (404) none of this renders.

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
  useNavigate: () => vi.fn(),
}));

vi.mock("../auth/session", async () => {
  const { ProblemError } = await import("../lib/problem");
  const idle = { mutate: vi.fn(), isPending: false };
  return {
    ProblemError,
    useLogin: () => idle,
    usePasskeyLogin: () => idle,
    useRegister: () => idle,
    useForgotPassword: () => idle,
  };
});

import { DemoBanner } from "../components/demo-banner";
import { fetchDemo, notifyDemoDisabled, resetDemoCache } from "../lib/demo";
import { ProblemError } from "../lib/problem";
import { queryClient as appQueryClient } from "../query";
import { ForgotPasswordPage } from "../routes/forgot-password";
import { LoginPage } from "../routes/login";
import { RegisterPage } from "../routes/register";

const DEMO = {
  enabled: true,
  email: "admin@custode.local",
  password: "custode-admin-demo",
  reset_interval_minutes: 60,
  resetting: false,
};

function answer(status: number, body: unknown = {}): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

function renderWithQuery(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider i18n={i18n}>{node}</I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetDemoCache();
  document.head.querySelectorAll('meta[name="robots"]').forEach((m) => m.remove());
});

describe("fetchDemo", () => {
  it("returns the demo info on a demo instance", async () => {
    answer(200, DEMO);
    expect(await fetchDemo()).toEqual(DEMO);
  });

  it("is null on a normal instance, on garbage and when the network fails", async () => {
    answer(404);
    expect(await fetchDemo()).toBeNull();
    answer(200, { enabled: false });
    expect(await fetchDemo()).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    expect(await fetchDemo()).toBeNull();
  });
});

describe("DemoBanner", () => {
  it("shows the hourly-reset warning, tells robots to stay away, has no axe violations", async () => {
    answer(200, DEMO);
    const { container } = renderWithQuery(<DemoBanner />);
    expect(
      await screen.findByText(
        "Demo — die Daten werden stündlich zurückgesetzt. Bitte keine persönlichen Daten eingeben.",
      ),
    ).toBeInTheDocument();
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow",
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it("says when a reset is running", async () => {
    answer(200, { ...DEMO, resetting: true });
    renderWithQuery(<DemoBanner />);
    expect(await screen.findByText(/werden gerade zurückgesetzt/)).toBeInTheDocument();
  });

  it("explains an action the server refused with demo_disabled", async () => {
    answer(200, DEMO);
    renderWithQuery(<DemoBanner />);
    await screen.findByRole("status");
    expect(screen.queryByText("Diese Aktion ist in der Demo abgeschaltet.")).toBeNull();
    // The app's query client routes the slug to the banner, whichever form failed.
    await act(async () => {
      await appQueryClient
        .getMutationCache()
        .build(appQueryClient, {
          mutationFn: async () => {
            throw new ProblemError("demo_disabled");
          },
        })
        .execute(undefined)
        .catch(() => {});
    });
    expect(screen.getByText("Diese Aktion ist in der Demo abgeschaltet.")).toBeInTheDocument();
  });

  it("renders nothing on a normal instance", async () => {
    answer(404);
    const { container } = renderWithQuery(<DemoBanner />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    act(() => notifyDemoDisabled());
    expect(container).toBeEmptyDOMElement();
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("auth pages in the demo", () => {
  it("prefills the shared login and hides sign-up and password reset", async () => {
    answer(200, DEMO);
    renderWithQuery(<LoginPage />);
    await waitFor(() => expect(screen.getByLabelText("E-Mail")).toHaveValue(DEMO.email));
    expect(screen.getByLabelText("Passwort")).toHaveValue(DEMO.password);
    expect(screen.getByText(/gemeinsame Zugang ist eingetragen/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Passwort vergessen/ })).toBeNull();
  });

  it("leaves the sign-in page alone on a normal instance", async () => {
    answer(404);
    renderWithQuery(<LoginPage />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.getByLabelText("E-Mail")).toHaveValue("");
    expect(screen.getByRole("link", { name: /Passwort vergessen/ })).toBeInTheDocument();
  });

  it("explains instead of offering sign-up and reset forms", async () => {
    answer(200, DEMO);
    renderWithQuery(<RegisterPage />);
    expect(await screen.findByText(/Registrierung ist in der Demo abgeschaltet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    renderWithQuery(<ForgotPasswordPage />);
    expect(await screen.findByText(/verschickt keine E-Mails/)).toBeInTheDocument();
  });
});
