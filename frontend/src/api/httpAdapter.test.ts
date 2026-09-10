import { createHttpApiClient } from "./httpAdapter";
import { ApiError, ForbiddenError, UnauthenticatedError } from "./errors";
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
    const fetchMock = vi.fn().mockResolvedValue(json({ devices: [{ id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycle_status: "active", last_seen_at: "2026-09-10T10:00:00Z", agent_version: "0.1.0" }, { id: "pending-1", name: "Pending host", platform: "linux/amd64", status: "offline", lifecycle_status: "pending", last_seen_at: null, agent_version: null }] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createHttpApiClient().devices.list()).resolves.toEqual([
      { id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T10:00:00Z", agentVersion: "0.1.0" },
      { id: "pending-1", name: "Pending host", platform: "linux/amd64", status: "offline", lifecycleStatus: "pending", lastSeenAt: null, agentVersion: null }
    ]);
  });

  it("clears memory and surfaces unauthenticated on a 401", async () => {
    accessTokenStore.replace("expired-access");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ message: "Invalid request." }, 401)));

    await expect(createHttpApiClient().devices.list()).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(accessTokenStore.read()).toBeUndefined();
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
});
