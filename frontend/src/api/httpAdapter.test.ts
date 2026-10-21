import { createHttpApiClient } from "./httpAdapter";
import { ApiError, ApiUnavailableError, ForbiddenError, UnauthenticatedError } from "./errors";
import { accessTokenStore } from "./memoryAccessToken";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function headersFor(fetchMock: ReturnType<typeof vi.fn>, call = 0): Headers {
  const request = fetchMock.mock.calls[call]?.[1] as RequestInit;
  return new Headers(request.headers);
}

describe("HTTP API adapter", () => {
  afterEach(() => {
    accessTokenStore.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("stores a login access token only in memory then uses it for /me", async () => {
    const persist = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ access_token: "access-from-login", token_type: "Bearer", expires_in: 600 }))
      .mockResolvedValueOnce(json({ id: "user-1", email: "person@example.test" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpApiClient();

    await api.auth.login({ email: "person@example.test", password: "correct-password" });
    expect(accessTokenStore.read()).toBe("access-from-login");
    expect(persist).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/login");
    expect(headersFor(fetchMock).get("Authorization")).toBeNull();

    await expect(api.auth.me()).resolves.toEqual({ id: "user-1", email: "person@example.test" });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/me");
    expect(headersFor(fetchMock, 1).get("Authorization")).toBe("Bearer access-from-login");
  });

  it("refreshes with the HttpOnly-cookie request path without forwarding a stale bearer", async () => {
    accessTokenStore.replace("stale-access");
    const fetchMock = vi.fn().mockResolvedValue(json({ access_token: "rotated-access", token_type: "Bearer", expires_in: 600 }));
    vi.stubGlobal("fetch", fetchMock);

    await createHttpApiClient().auth.refresh();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/refresh");
    expect(headersFor(fetchMock).get("Authorization")).toBeNull();
    expect(headersFor(fetchMock).get("Accept")).toBe("application/json");
    expect(accessTokenStore.read()).toBe("rotated-access");
  });

  it("serializes concurrent refresh calls so a rotating cookie is not replayed", async () => {
    let resolveResponse: (response: Response) => void = () => undefined;
    const response = new Promise<Response>((resolve) => { resolveResponse = resolve; });
    const fetchMock = vi.fn().mockReturnValue(response);
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpApiClient();

    const first = api.auth.refresh();
    const second = api.auth.refresh();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveResponse(json({ access_token: "one-refresh", token_type: "Bearer", expires_in: 600 }));
    await expect(Promise.all([first, second])).resolves.toEqual([undefined, undefined]);
  });

  it("parses only the real server device contract", async () => {
    accessTokenStore.replace("access-token");
    const fetchMock = vi.fn().mockResolvedValue(json({ devices: [{ id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycle_status: "active", last_seen_at: "2026-09-10T10:00:00Z", agent_version: "0.1.0", fingerprint: null }, { id: "pending-1", name: "Pending host", platform: "linux/amd64", status: "offline", lifecycle_status: "pending", last_seen_at: null, agent_version: null, fingerprint: "SHA256:exact=" }] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createHttpApiClient().devices.list()).resolves.toEqual([
      { id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T10:00:00Z", agentVersion: "0.1.0", fingerprint: null, telemetry: null },
      { id: "pending-1", name: "Pending host", platform: "linux/amd64", status: "offline", lifecycleStatus: "pending", lastSeenAt: null, agentVersion: null, fingerprint: "SHA256:exact=", telemetry: null }
    ]);
  });

  it("parses device telemetry and rejects malformed telemetry", async () => {
    accessTokenStore.replace("access-token");
    const base = { id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycle_status: "active", last_seen_at: "2026-09-10T10:00:00Z", agent_version: "0.1.0", fingerprint: null };
    const wire = { recorded_at: "2026-10-21T12:00:00Z", cpu_percent: 12.5, load1: null, cpu_count: 8, memory_total_bytes: 100, memory_used_bytes: 40, disk_total_bytes: null, disk_used_bytes: null, temperature_c: 48, uptime_seconds: 60 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ devices: [{ ...base, telemetry: wire }] })));
    await expect(createHttpApiClient().devices.list()).resolves.toEqual([expect.objectContaining({
      telemetry: { recordedAt: "2026-10-21T12:00:00Z", cpuPercent: 12.5, load1: null, cpuCount: 8, memoryTotalBytes: 100, memoryUsedBytes: 40, diskTotalBytes: null, diskUsedBytes: null, temperatureC: 48, uptimeSeconds: 60 }
    })]);
    for (const bad of [{ ...wire, cpu_percent: "12" }, { ...wire, recorded_at: "never" }, "x", { ...wire, uptime_seconds: undefined }]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ devices: [{ ...base, telemetry: bad }] })));
      await expect(createHttpApiClient().devices.list()).rejects.toThrow("invalid response");
    }
  });

  it("clears memory and surfaces unauthenticated on a 401", async () => {
    accessTokenStore.replace("expired-access");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ message: "Invalid request." }, 401)));

    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(accessTokenStore.read()).toBeUndefined();
  });

  it("refreshes once after an authenticated 401 and retries with the rotated bearer", async () => {
    accessTokenStore.replace("expired-access");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(json({ access_token: "rotated-access", token_type: "Bearer", expires_in: 600 }))
      .mockResolvedValueOnce(json({ devices: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createHttpApiClient().devices.list()).resolves.toEqual([]);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/devices", "/api/v1/auth/refresh", "/api/v1/devices"
    ]);
    expect(headersFor(fetchMock, 0).get("Authorization")).toBe("Bearer expired-access");
    expect(headersFor(fetchMock, 1).get("Authorization")).toBeNull();
    expect(headersFor(fetchMock, 2).get("Authorization")).toBe("Bearer rotated-access");
  });

  it("does not refresh recursively when refresh itself is rejected", async () => {
    accessTokenStore.replace("expired-access");
    const fetchMock = vi.fn().mockResolvedValue(json({}, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/devices", "/api/v1/auth/refresh"]);
    expect(accessTokenStore.read()).toBeUndefined();
  });

  it.each([
    ["503", () => json({}, 503)],
    ["network failure", () => Promise.reject(new TypeError("network down"))]
  ])("preserves refresh %s as unavailable without clearing access", async (_name, refreshResponse) => {
    accessTokenStore.replace("expired-access");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 401))
      .mockImplementationOnce(refreshResponse);
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(ApiUnavailableError);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/devices", "/api/v1/auth/refresh"]);
    expect(accessTokenStore.read()).toBe("expired-access");
  });

  it("shares one automatic refresh across concurrent expired authenticated requests", async () => {
    accessTokenStore.replace("expired-access");
    let resolveRefresh: (response: Response) => void = () => undefined;
    const refresh = new Promise<Response>((resolve) => { resolveRefresh = resolve; });
    let deviceCalls = 0;
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/refresh") return refresh;
      deviceCalls += 1;
      return Promise.resolve(deviceCalls <= 2 ? json({}, 401) : json({ devices: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpApiClient();
    const first = api.devices.list();
    const second = api.devices.list();
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock.mock.calls.filter((call) => call[0] === "/api/v1/auth/refresh")).toHaveLength(1);
    resolveRefresh(json({ access_token: "rotated-access", token_type: "Bearer", expires_in: 600 }));
    await expect(Promise.all([first, second])).resolves.toEqual([[], []]);
  });

  it("preserves the access token and a typed forbidden error on a 403", async () => {
    accessTokenStore.replace("still-valid-access");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ code: "DEVICE_REVOKED" }, 403)));

    let rejected: unknown;
    try {
      await createHttpApiClient().devices.list();
    } catch (error) {
      rejected = error;
    }
    expect(rejected).toBeInstanceOf(ForbiddenError);
    expect(rejected).not.toBeInstanceOf(UnauthenticatedError);
    expect(rejected).toMatchObject({ status: 403, code: "DEVICE_REVOKED" });
    expect(accessTokenStore.read()).toBe("still-valid-access");
  });

  it("rejects a malformed API body rather than accepting a provisional contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ devices: [{ id: "PC000" }] })));
    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(ApiError);
  });

  it("clears the in-memory token after logout", async () => {
    accessTokenStore.replace("access-to-revoke");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await createHttpApiClient().auth.logout();
    expect(headersFor(fetchMock).get("Authorization")).toBe("Bearer access-to-revoke");
    expect(accessTokenStore.read()).toBeUndefined();
  });
  it("uses real pairing and decision endpoints without persisting the pairing secret", async () => {
    const persist = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ pairing_id: "pairing-id", pairing_token: "ephemeral-pairing", expires_at: "2026-09-12T12:00:00Z" }, 201))
      .mockResolvedValue(json({}));
    vi.stubGlobal("fetch", fetchMock);
    accessTokenStore.replace("authenticated-access");
    const api = createHttpApiClient();
    await expect(api.devices.createPairing()).resolves.toEqual({ pairingId: "pairing-id", pairingToken: "ephemeral-pairing", expiresAt: "2026-09-12T12:00:00Z" });
    await api.devices.approve("device/id", "SHA256:AbC+/exact=");
    await api.devices.reject("device/id", "SHA256:AbC+/exact=");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/devices/pairings", "/api/v1/devices/device%2Fid/approve", "/api/v1/devices/device%2Fid/reject"]);
    expect(fetchMock.mock.calls.map((call) => (call[1] as RequestInit).method)).toEqual(["POST", "POST", "POST"]);
    expect(fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string))).toEqual([{}, { fingerprint: "SHA256:AbC+/exact=" }, { fingerprint: "SHA256:AbC+/exact=" }]);
    expect(headersFor(fetchMock).get("Authorization")).toBe("Bearer authenticated-access");
    expect(persist).not.toHaveBeenCalled();
    expect(accessTokenStore.read()).toBe("authenticated-access");
  });

  it("rejects a device fixture missing the required fingerprint", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ devices: [{ id: "legacy", name: "Legacy", platform: "linux", status: "offline", lifecycle_status: "active", last_seen_at: null, agent_version: null }] })));
    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(ApiError);
  });

  it.each(["createPairing", "approve", "reject"] as const)("keeps typed auth errors for %s", async (method) => {
    const api = createHttpApiClient();
    const call = (): Promise<unknown> => method === "createPairing" ? api.devices.createPairing() : api.devices[method]("device", "SHA256:exact");
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(json({}, 401)));
    accessTokenStore.replace("valid-access");
    await expect(call()).rejects.toBeInstanceOf(ForbiddenError);
    expect(accessTokenStore.read()).toBe("valid-access");
    await expect(call()).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(accessTokenStore.read()).toBeUndefined();
  });

  it("rejects an invalid pairing expiry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ pairing_id: "pairing-id", pairing_token: "ephemeral", expires_at: "invalid" }, 201)));
    await expect(createHttpApiClient().devices.createPairing()).rejects.toBeInstanceOf(ApiError);
  });

});
