import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ApiClient } from "../api";
import { RegisterPage } from "./RegisterPage";
import { VerifyPage } from "./VerifyPage";

function api(overrides: Partial<ApiClient["auth"]> = {}): ApiClient {
  return {
    auth: {
      register: vi.fn(async () => ({ message: "ok" })),
      consumeVerificationCode: vi.fn(async () => ({ verified: true })),
      login: async () => undefined, refresh: async () => undefined, logout: async () => undefined,
      me: async () => ({ id: "u", email: "a@example.test" }),
      resendVerification: vi.fn(async () => undefined),
      ...overrides
    },
    devices: { list: async () => [], createPairing: vi.fn(), revokePairing: vi.fn(), approve: vi.fn(), reject: vi.fn() }
  } as ApiClient;
}

describe("Register and verify", () => {
  afterEach(() => { window.history.pushState({}, "", "/"); window.sessionStorage.clear(); });

  it("explains the 15-character rule before calling the server", () => {
    const client = api();
    render(<RegisterPage api={client} />);
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "curta" } });
    expect(screen.getByText(/faltam 10/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    expect(screen.getByRole("alert")).toHaveTextContent("pelo menos 15 caracteres");
    expect(client.auth.register).not.toHaveBeenCalled();
  });

  it("registers and moves to the verification page remembering the e-mail", async () => {
    const client = api();
    render(<RegisterPage api={client} />);
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "voce@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "minha senha do aval 2026" } });
    fireEvent.change(screen.getByLabelText("Repita a senha"), { target: { value: "minha senha do aval 2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    await waitFor(() => expect(window.location.pathname).toBe("/verify"));
    expect(window.sessionStorage.getItem("aval.pending-email")).toBe("voce@example.test");
  });

  it("uses the challenge from the e-mail link so only the code is typed", async () => {
    const challenge = "3f2a9c1e-1111-4222-8333-444455556666";
    window.history.pushState({}, "", `/verify?challenge=${challenge}`);
    const client = api();
    render(<VerifyPage api={client} />);
    expect(screen.queryByLabelText("Identificador do e-mail")).toBeNull();
    fireEvent.change(screen.getByLabelText("Código de 8 números"), { target: { value: "1234 5678" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar e-mail" }));
    expect(await screen.findByRole("heading", { name: "E-mail confirmado" })).toBeVisible();
    expect(client.auth.consumeVerificationCode).toHaveBeenCalledWith({ challenge_id: challenge, code: "1234 5678" });
  });

  it("offers to resend the code to the e-mail just registered", async () => {
    window.sessionStorage.setItem("aval.pending-email", "voce@example.test");
    const client = api();
    render(<VerifyPage api={client} />);
    expect(screen.getByText("voce@example.test")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Enviar outro código" }));
    expect(await screen.findByText(/Pedimos um novo código/)).toBeVisible();
    expect(client.auth.resendVerification).toHaveBeenCalledWith("voce@example.test");
  });
});
