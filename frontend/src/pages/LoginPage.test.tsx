import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ApiClient } from "../api";
import { UnauthenticatedError } from "../api";
import { SessionProvider } from "../app/session";
import { LoginPage } from "./LoginPage";

function fakeClient(login: ApiClient["auth"]["login"] = async () => undefined): ApiClient {
  return {
    auth: {
      register: async () => ({ message: "" }),
      consumeVerificationCode: async () => ({ verified: true }),
      login,
      refresh: async () => { throw new UnauthenticatedError(); },
      logout: async () => undefined,
      me: async () => ({ id: "user-1", email: "operator@example.test" })
    },
    devices: { list: async () => [], createPairing: async () => ({ pairingId: "pairing", pairingToken: "test-only", expiresAt: "2026-09-12T12:00:00Z" }), revokePairing: async () => undefined, approve: async () => undefined, reject: async () => undefined }
  };
}

function renderLogin(api: ApiClient = fakeClient()): void {
  render(<SessionProvider api={api}><LoginPage /></SessionProvider>);
}

async function waitForLoginForm(): Promise<void> {
  await waitFor(() => expect(screen.getByRole("button", { name: "Entrar no Device Center" })).not.toBeDisabled());
}

describe("LoginPage", () => {
  it("renders the approved trust-focused composition and recovery notice", async () => {
    renderLogin();
    await waitForLoginForm();
    expect(screen.getByText("Camada de confiança / v2")).toBeVisible();
    expect(screen.getByText("Espaço pessoal")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Veja o que está seguro e pronto." })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Esqueci minha senha" }));
    expect(screen.getByText("Recuperação de conta ainda não está disponível nesta versão.")).toBeVisible();
  });

  it("provides an accessible password visibility control", async () => {
    renderLogin();
    await waitForLoginForm();
    const input = screen.getByLabelText("Senha");
    const toggle = screen.getByRole("button", { name: "Mostrar senha" });
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
  });

  it("shows the approved loading label while real login is pending", async () => {
    renderLogin(fakeClient(async () => new Promise<void>(() => undefined)));
    await waitForLoginForm();
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "demo@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "not-a-real-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar no Device Center" }));
    expect(screen.getByRole("button", { name: "Entrando no Device Center…" })).toBeDisabled();
  });
});
