import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DevicesApi } from "../api/client";
import type { DeviceTelemetry } from "../api/contracts";
import { DeviceChart } from "./DeviceChart";

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
});
