import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AdminApi } from "../api/client";
import { AdminPanel } from "./AdminPanel";

function fakeAdmin(): AdminApi {
  return {
    overview: vi.fn(async () => ({ checkedAt: "2026-10-21T22:00:00Z", users: { active: 2, pending_verification: 1 }, devicesByLifecycle: { active: 2 }, devicesOnline: 2, commands24h: { delivered: 3, failed: 1 }, telegramLinks: 1 })),
    users: vi.fn(async () => [
      { id: "11111111-1111-4111-8111-111111111111", email: "voide@example.test", status: "active", role: "admin", createdAt: "2026-10-21T10:00:00Z", devices: 2, telegram: true, pin: true },
      { id: "22222222-2222-4222-8222-222222222222", email: "novo@example.test", status: "pending_verification", role: "user", createdAt: "2026-10-21T11:00:00Z", devices: 0, telegram: false, pin: false }
    ]),
    failures: vi.fn(async () => [{ at: "2026-10-21T12:00:00Z", user: "voide@example.test", device: "tropa", action: "lock_screen", status: "failed", error: "unsupported" }]),
    events: vi.fn(async () => [{ occurredAt: "2026-10-21T12:00:00Z", user: "voide@example.test", action: "auth.login", outcome: "success" }]),
    activate: vi.fn(async () => undefined)
  };
}

describe("AdminPanel", () => {
  it("shows health, accounts, failures and lets the admin activate a pending account", async () => {
    const api = fakeAdmin();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AdminPanel api={api} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Administração" })).toBeVisible();
    expect(screen.getByText("2 de 2")).toBeVisible();
    expect(screen.getByText("1 com falha ou negadas")).toBeVisible();
    expect(screen.getByText("bloquear tela")).toBeVisible();
    expect(screen.getByText("aguardando e-mail")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Ativar conta" }));
    await waitFor(() => expect(api.activate).toHaveBeenCalledWith("22222222-2222-4222-8222-222222222222"));
    expect(await screen.findByText("Conta novo@example.test ativada.")).toBeVisible();
  });
});
