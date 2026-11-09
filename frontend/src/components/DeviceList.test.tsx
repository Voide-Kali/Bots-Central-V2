import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Device, DeviceTelemetry } from "../api/contracts";
import { DeviceList } from "./DeviceList";

function telemetry(secondsAgo: number): DeviceTelemetry {
  return {
    recordedAt: new Date(Date.now() - secondsAgo * 1000).toISOString(),
    cpuPercent: 12, load1: null, cpuCount: 4,
    memoryTotalBytes: 100, memoryUsedBytes: 40,
    diskTotalBytes: 200, diskUsedBytes: 50,
    temperatureC: 40, uptimeSeconds: 3600
  };
}

function device(overrides: Partial<Device>): Device {
  return {
    id: "d1", name: "meu-pc", platform: "linux/amd64",
    status: "online", lifecycleStatus: "active",
    lastSeenAt: new Date(Date.now() - 30_000).toISOString(),
    agentVersion: "0.5.0", fingerprint: "SHA256:abc",
    telemetry: telemetry(40),
    network: { publicIp: "203.0.113.7", localIps: ["192.168.0.10"], reportedAt: new Date(Date.now() - 600_000).toISOString() },
    ...overrides
  };
}

describe("DeviceList staleness", () => {
  it("flags telemetry and IP as possibly outdated when the computer is offline", () => {
    render(<DeviceList devices={[device({ status: "offline" })]} selectedId="d1" onSelect={vi.fn()} />);
    expect(screen.getByText(/computador offline, pode estar desatualizada/i)).toBeInTheDocument();
    expect(screen.getAllByText(/pode estar desatualizado/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/reportado há/i)).toBeInTheDocument();
  });

  it("shows when telemetry and IP were received without a stale flag when online", () => {
    render(<DeviceList devices={[device({ status: "online" })]} selectedId="d1" onSelect={vi.fn()} />);
    expect(screen.getAllByText(/Telemetria recebida/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/reportado há/i)).toBeInTheDocument();
    expect(screen.queryByText(/pode estar desatualizad/i)).not.toBeInTheDocument();
  });
});
