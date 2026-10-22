import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionPinApi } from "../api/client";
import { ApiError, ForbiddenError } from "../api/errors";
import { PinCard } from "./PinCard";

function fill(pin: string, again: string, password = "senha da conta longa"): void {
  fireEvent.change(screen.getByLabelText("PIN (6 números)"), { target: { value: pin } });
  fireEvent.change(screen.getByLabelText("Repita o PIN"), { target: { value: again } });
  fireEvent.change(screen.getByLabelText("Senha da conta"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Salvar PIN" }));
}

describe("PinCard", () => {
  it("creates a PIN after local checks", async () => {
    const api: ActionPinApi = { status: vi.fn(async () => ({ configured: false, lockedUntil: null })), set: vi.fn(async () => undefined) };
    render(<PinCard api={api} onUnauthenticated={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Criar PIN" }));
    fill("12345", "12345");
    expect(screen.getByRole("alert")).toHaveTextContent("exatamente 6 números");
    fill("482913", "482914");
    expect(screen.getByRole("alert")).toHaveTextContent("diferentes");
    expect(api.set).not.toHaveBeenCalled();
    fill("482913", "482913");
    await waitFor(() => expect(api.set).toHaveBeenCalledWith("senha da conta longa", "482913"));
    expect(await screen.findByText(/PIN salvo/)).toBeVisible();
  });

  it("explains wrong password and weak PIN", async () => {
    const api: ActionPinApi = { status: vi.fn(async () => ({ configured: true, lockedUntil: null })), set: vi.fn(async () => { throw new ForbiddenError(); }) };
    render(<PinCard api={api} onUnauthenticated={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Trocar PIN" }));
    fill("482913", "482913");
    expect(await screen.findByText("Senha da conta incorreta.")).toBeVisible();
    api.set = vi.fn(async () => { throw new ApiError("weak", 422); });
    fill("482913", "482913");
    expect(await screen.findByText(/fácil demais/)).toBeVisible();
  });
});
