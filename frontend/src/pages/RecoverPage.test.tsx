import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api";
import { ApiError } from "../api";
import { RecoverPage } from "./RecoverPage";

function client(confirm = vi.fn(async () => undefined)): ApiClient {
  return {
    auth: {} as ApiClient["auth"],
    devices: {} as ApiClient["devices"],
    passwordReset: { request: vi.fn(async () => undefined), confirm }
  };
}

function fill(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("RecoverPage", () => {
  it("requests a code, then changes the password", async () => {
    const api = client();
    render(<RecoverPage api={api} />);
    fill("E-mail da conta", " voce@example.com ");
    fireEvent.click(screen.getByRole("button", { name: "Enviar código" }));
    expect(await screen.findByText(/um código foi enviado para voce@example.com/)).toBeVisible();
    expect(api.passwordReset?.request).toHaveBeenCalledWith("voce@example.com");
    fill("Código de 8 dígitos", "1234 5678");
    fill("Senha nova", "uma senha nova bem longa");
    fill("Confirmar senha nova", "uma senha nova bem longa");
    fireEvent.click(screen.getByRole("button", { name: "Alterar senha" }));
    expect(await screen.findByText("Senha alterada. Entre de novo com a senha nova.")).toBeVisible();
    expect(api.passwordReset?.confirm).toHaveBeenCalledWith({ email: "voce@example.com", code: "12345678", newPassword: "uma senha nova bem longa" });
  });

  it("explains invalid codes and mismatched passwords", async () => {
    const confirm = vi.fn(async () => { throw new ApiError("bad", 400); });
    render(<RecoverPage api={client(confirm)} />);
    fill("E-mail da conta", "voce@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Enviar código" }));
    await screen.findByLabelText("Código de 8 dígitos");
    fill("Código de 8 dígitos", "00000000");
    fill("Senha nova", "uma senha nova bem longa");
    fill("Confirmar senha nova", "outra senha diferente aqui");
    fireEvent.click(screen.getByRole("button", { name: "Alterar senha" }));
    expect(await screen.findByText("As senhas não coincidem.")).toBeVisible();
    expect(confirm).not.toHaveBeenCalled();
    fill("Confirmar senha nova", "uma senha nova bem longa");
    fireEvent.click(screen.getByRole("button", { name: "Alterar senha" }));
    await waitFor(() => expect(screen.getByText(/Código inválido ou expirado/)).toBeVisible());
  });
});
