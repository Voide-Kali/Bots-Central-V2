import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionPinApi, DevicesApi } from "../api/client";
import type { StartActionResult, WebActionStatus } from "../api/contracts";
import { DeviceActions } from "./DeviceActions";

function baseApi(overrides: Partial<DevicesApi>): DevicesApi {
  return { list: vi.fn(), createPairing: vi.fn(), revokePairing: vi.fn(), approve: vi.fn(), reject: vi.fn(), ...overrides };
}

function pin(configured: boolean): ActionPinApi {
  return { status: vi.fn(async () => ({ configured, lockedUntil: null })), set: vi.fn() };
}

function typePin(value: string): void {
  fireEvent.change(screen.getByLabelText("PIN de 6 números"), { target: { value } });
}

describe("DeviceActions", () => {
  it("guides the owner to create a PIN first when none is set", async () => {
    render(<DeviceActions api={baseApi({ startAction: vi.fn(), actionStatus: vi.fn() })} pinApi={pin(false)} deviceId="d1" onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText(/crie um PIN/i)).toBeVisible();
  });

  it("runs a network scan with the PIN and shows the result text", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const start = vi.fn(async (): Promise<StartActionResult> => ({ ok: true, commandId: "c1" }));
    const status = vi.fn(async (): Promise<WebActionStatus> => ({ status: "completed", message: "Rede de tropa verificada.", text: "2 aparelhos\n192.168.1.1 - gw", hasPhoto: false }));
    render(<DeviceActions api={baseApi({ startAction: start, actionStatus: status })} pinApi={pin(true)} deviceId="d1" onUnauthenticated={vi.fn()} />);
    await screen.findByText("Ações");
    typePin("482913");
    fireEvent.click(screen.getByRole("button", { name: "Rede" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(start).toHaveBeenCalledWith("d1", "network_scan", "482913");
    expect(screen.getByText("Rede de tropa verificada.")).toBeVisible();
    expect(screen.getByText(/192\.168\.1\.1 - gw/)).toBeVisible();
    vi.useRealTimers();
  });

  it("reports a wrong PIN without polling", async () => {
    const start = vi.fn(async (): Promise<StartActionResult> => ({ ok: false, reason: "wrong_pin" }));
    const status = vi.fn();
    render(<DeviceActions api={baseApi({ startAction: start, actionStatus: status })} pinApi={pin(true)} deviceId="d1" onUnauthenticated={vi.fn()} />);
    await screen.findByText("Ações");
    typePin("000000");
    fireEvent.click(screen.getByRole("button", { name: "Bloquear tela" }));
    expect(await screen.findByText("PIN incorreto.")).toBeVisible();
    expect(status).not.toHaveBeenCalled();
  });

  it("asks for a 6-digit PIN before doing anything", async () => {
    const start = vi.fn();
    render(<DeviceActions api={baseApi({ startAction: start, actionStatus: vi.fn() })} pinApi={pin(true)} deviceId="d1" onUnauthenticated={vi.fn()} />);
    await screen.findByText("Ações");
    typePin("12");
    fireEvent.click(screen.getByRole("button", { name: "Foto" }));
    expect(await screen.findByText("Digite o seu PIN de 6 números.")).toBeVisible();
    expect(start).not.toHaveBeenCalled();
  });
});
