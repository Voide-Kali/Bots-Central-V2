import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DevicesApi } from "../api/client";
import type { DeviceTelemetry } from "../api/contracts";
import { DeviceChart, telemetryToCsv } from "./DeviceChart";

function sample(secondsAgo: number, cpu: number): DeviceTelemetry {
  return { recordedAt: new Date(Date.now() - secondsAgo * 1000).toISOString(), cpuPercent: cpu, load1: null, cpuCount: 4, memoryTotalBytes: 100, memoryUsedBytes: 40, diskTotalBytes: null, diskUsedBytes: null, temperatureC: null, uptimeSeconds: 10 };
}

function api(rows: readonly DeviceTelemetry[]): DevicesApi {
  return { list: vi.fn(), createPairing: vi.fn(), revokePairing: vi.fn(), approve: vi.fn(), reject: vi.fn(), history: vi.fn(async () => rows), watch: vi.fn(async () => undefined) };
}

describe("DeviceChart", () => {
  it("asks for live samples, shows the latest value and marks the peak", async () => {
    const devices = api([sample(3, 12), sample(2, 87.5), sample(1, 30)]);
    render(<DeviceChart api={devices} deviceId="d1" onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("pico 87,5 · baixa 12 · média 43,2")).toBeVisible();
    expect(screen.getByRole("img", { name: "CPU: 30 %" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Memória: 40 %" })).toBeVisible();
    expect(screen.queryByText("Temperatura")).toBeNull(); // no sensor, no empty chart
    expect(devices.watch).toHaveBeenCalledWith("d1");
    expect(devices.history).toHaveBeenCalledWith("d1", 2);
    expect(screen.getByText("Ao vivo, 1 medição por segundo")).toBeVisible();
  });

  it("refreshes every second while live", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const devices = api([sample(1, 10)]);
    render(<DeviceChart api={devices} deviceId="d1" onUnauthenticated={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect((devices.history as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(3);
    vi.useRealTimers();
  });

  it("shows an isolated sample as a point instead of drawing a false line across a gap", async () => {
    const devices = api([sample(80, 30), sample(2, 40), sample(1, 45)]);
    render(<DeviceChart api={devices} deviceId="d1" onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("pico 45 · baixa 30 · média 38,3")).toBeVisible();
    expect(document.querySelectorAll(".chart__sample")).toHaveLength(2);
    expect(document.querySelectorAll(".chart__line")).toHaveLength(2);
  });

  it("offers a CSV export of the samples", async () => {
    const devices = api([sample(2, 20), sample(1, 25)]);
    render(<DeviceChart api={devices} deviceId="d1" onUnauthenticated={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Exportar CSV" })).toBeEnabled();
  });

  it("hides the CSV export in read-only mode", async () => {
    const devices = api([sample(1, 10)]);
    render(<DeviceChart api={devices} deviceId="d1" exportable={false} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("Ao vivo, 1 medição por segundo")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Exportar CSV" })).toBeNull();
  });

  it("builds a semicolon CSV, oldest first, with pt-BR decimals", () => {
    const newer: DeviceTelemetry = { recordedAt: "2026-10-21T10:00:05Z", cpuPercent: 30, load1: 0.5, cpuCount: 4, memoryTotalBytes: 100, memoryUsedBytes: 40, diskTotalBytes: 200, diskUsedBytes: 50, temperatureC: 51.5, uptimeSeconds: 90 };
    const older: DeviceTelemetry = { recordedAt: "2026-10-21T10:00:01Z", cpuPercent: 12.2, load1: null, cpuCount: 4, memoryTotalBytes: 100, memoryUsedBytes: 25, diskTotalBytes: null, diskUsedBytes: null, temperatureC: null, uptimeSeconds: 10 };
    const lines = telemetryToCsv([newer, older]).split("\r\n");
    expect(lines[0]).toBe('"Quando";"CPU (%)";"Memória (%)";"Disco (%)";"Temperatura (°C)";"Carga (1 min)";"Uptime (s)";"Quando (ISO)"');
    expect(lines[1]).toContain('"2026-10-21T10:00:01Z"'); // oldest first
    expect(lines[1]).toContain('"12,2"');
    expect(lines[1]).toContain('"25,0"');
    expect(lines[2]).toContain('"51,5"');
    expect(lines[2]).toContain('"0,50"');
    expect(lines[2]).toContain('"25,0"'); // disk 50/200
  });
});
