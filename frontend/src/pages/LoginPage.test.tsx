import { fireEvent, render, screen } from "@testing-library/react";
import type { ApiClient } from "../api";
import type { LoginResult } from "../api/contracts";
import { SessionProvider } from "../app/session";
import { createMockApiClient } from "../api/mockAdapter";
import { LoginPage } from "./LoginPage";

function renderLogin(api: ApiClient = createMockApiClient()): void {
  render(<SessionProvider api={api}><LoginPage api={api} /></SessionProvider>);
}

describe("LoginPage", () => {
  it("renders the approved trust-focused composition and recovery notice", () => {
    renderLogin();
    expect(screen.getByText("Camada de confiança / v2")).toBeVisible();
    expect(screen.getByText("Espaço pessoal")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Veja o que está seguro e pronto." })).toBeVisible();
    expect(screen.getByText("Acesso seguro")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Esqueci minha senha" }));
    expect(screen.getByText("Recuperação de conta ainda não está disponível nesta versão.")).toBeVisible();
  });

  it("provides an accessible password visibility control", () => {
    renderLogin();
    const input = screen.getByLabelText("Senha");
    const toggle = screen.getByRole("button", { name: "Mostrar senha" });
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Ocultar senha" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the approved loading label while login is pending", () => {
    const api: ApiClient = {
      adapterName: "mock",
      auth: {
        register: async () => ({ message: "" }),
        consumeVerificationCode: async () => ({ verified: true }),
        login: async () => new Promise<LoginResult>(() => undefined),
        refresh: async () => ({ kind: "mock", displayName: "Demo" }),
        logout: async () => undefined,
        me: async () => ({ kind: "mock", displayName: "Demo" })
      },
      devices: { list: async () => ({ kind: "mock", devices: [] }) }
    };
    renderLogin(api);
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "demo@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "not-a-real-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar no Device Center" }));
    expect(screen.getByRole("button", { name: "Entrando no Device Center…" })).toBeDisabled();
  });
});
