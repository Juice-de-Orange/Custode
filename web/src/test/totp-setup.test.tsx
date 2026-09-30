import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { TotpSetup } from "../components/totp-setup";
import { i18n } from "../i18n";

type Props = Parameters<typeof TotpSetup>[0];

function renderTotp(overrides: Partial<Props> = {}) {
  const handlers = {
    onSetup: vi.fn(),
    onEnable: vi.fn(),
    onDisable: vi.fn(),
    onRegenerate: vi.fn(),
    onAcknowledgeCodes: vi.fn(),
  };
  const result = render(
    <I18nProvider i18n={i18n}>
      <TotpSetup
        enabled={false}
        setupData={null}
        recoveryCodes={null}
        error={null}
        setupPending={false}
        enablePending={false}
        disablePending={false}
        regeneratePending={false}
        {...handlers}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { ...handlers, ...result };
}

const SETUP = {
  secret: "ABC123SECRET",
  otpauth_uri: "otpauth://totp/Custode:a@b.de?secret=ABC123SECRET&issuer=Custode",
};

test("offers to set up 2FA when inactive", () => {
  const { onSetup } = renderTotp();
  fireEvent.click(screen.getByRole("button", { name: "Zwei-Faktor einrichten" }));
  expect(onSetup).toHaveBeenCalledOnce();
});

test("renders the QR, the manual secret and a code field once setup started", () => {
  const { onEnable, container } = renderTotp({ setupData: SETUP });
  expect(container.querySelector("svg")).not.toBeNull(); // the QR code
  expect(screen.getByText("ABC123SECRET")).toBeInTheDocument(); // manual fallback
  fireEvent.change(screen.getByLabelText("Code aus der App"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Aktivieren" }));
  expect(onEnable).toHaveBeenCalledWith("123456");
});

test("shows the one-time recovery codes with a download and acknowledge", () => {
  const codes = Array.from({ length: 10 }, (_, i) => `code-${i}`);
  const { onAcknowledgeCodes } = renderTotp({ recoveryCodes: codes });
  for (const code of codes) expect(screen.getByText(code)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Herunterladen" })).toBeInTheDocument();
  expect(screen.getByText("Bewahre diese Codes sicher auf — sie werden nur jetzt angezeigt.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ich habe sie gespeichert" }));
  expect(onAcknowledgeCodes).toHaveBeenCalledOnce();
});

test("shows an error message during setup", () => {
  renderTotp({ setupData: SETUP, error: "security.error.totpInvalid" });
  expect(screen.getByRole("alert")).toHaveTextContent("Code ungültig. Bitte erneut versuchen.");
});

test("disables and regenerates when 2FA is active", () => {
  const { onDisable, onRegenerate } = renderTotp({ enabled: true });
  expect(screen.getByText("Zwei-Faktor-Authentisierung ist aktiv.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Code aus der App"), { target: { value: "654321" } });
  fireEvent.click(screen.getByRole("button", { name: "Deaktivieren" }));
  expect(onDisable).toHaveBeenCalledWith("654321");
  fireEvent.click(screen.getByRole("button", { name: "Recovery-Codes neu erzeugen" }));
  expect(onRegenerate).toHaveBeenCalledOnce();
});
