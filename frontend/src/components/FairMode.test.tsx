import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api";
import type { AuditEvent, Device, DeviceTelemetry } from "../api/contracts";
import { FairMode } from "./FairMode";

function telemetry(cpu: number): DeviceTelemetry {
  return { recordedAt: new Date().toISOString(), cpuPercent: cpu, load1: null, cpuCount: 4, memoryTotalBytes: 100, memoryUsedBytes: 40, diskTotalBytes: 100, diskUsedBytes: 20, temperatureC: 48, uptimeSeconds: 10 };
}

function device(name: string, status: "online" | "offline", cpu: number): Device {
  return { id: name, name, platform: "linux", status, lifecycleStatus: "active", fingerprint: null, agentVersion: "0.5.0", lastSeenAt: new Date().toISOString(), telemetry: telemetry(cpu) };
}

const event: AuditEvent = { occurredAt: new Date().toISOString(), actor: "device", action: "action.completed", outcome: "ok", name: "tropa", kind: "lock_screen", file: null, byPin: true, source: null };

function api(devices: readonly Device[], events: readonly AuditEvent[]): ApiClient {
  return {
    devices: {
      list: vi.fn(async () => devices), createPairing: vi.fn(), revokePairing: vi.fn(), approve: vi.fn(), reject: vi.fn(),
      history: vi.fn(async () => [telemetry(30)]), watch: vi.fn(async () => undefined)
    },
    audit: { list: vi.fn(async () => events) }
  } as unknown as ApiClient;
}

describe("FairMode", () => {
  it("shows the fleet, a PROTEGIDO status when all online, and the live activity feed", async () => {
    render(<FairMode api={api([device("tropa", "online", 72), device("MacMaker", "online", 15)], [event])} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("PROTEGIDO")).toBeVisible();
    expect(screen.getByText("2 de 2 online")).toBeVisible();
    // Fleet tiles with the computers and their CPU.
    expect(screen.getAllByText("tropa").length).toBeGreaterThan(0);
    expect(screen.getByText("72")).toBeVisible();
    expect(screen.getByText("MacMaker")).toBeVisible();
    // The live activity feed shows the friendly label of the event.
    expect(await screen.findByText("Ação concluída pelo agente")).toBeVisible();
  });

  it("warns when a computer is offline", async () => {
    render(<FairMode api={api([device("tropa", "online", 10), device("MacMaker", "offline", 0)], [])} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("ATENCAO")).toBeVisible();
    expect(screen.getByText("1 de 2 online")).toBeVisible();
    expect(screen.getByText("Aguardando atividade...")).toBeVisible();
  });
});
