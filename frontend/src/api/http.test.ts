import { ApiUnavailableError, UnauthenticatedError } from "./errors";
import { SameOriginHttpClient } from "./http";
import { accessTokenStore } from "./memoryAccessToken";

describe("SameOriginHttpClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    accessTokenStore.clear();
  });

  it("retries once with the rotated bearer after a successful refresh", async () => {
    accessTokenStore.replace("old-token");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new SameOriginHttpClient();
    client.setRefreshHandler(async () => { accessTokenStore.replace("new-token"); });
    await expect(client.get("/api/v1/devices")).resolves.toBeInstanceOf(Response);
    expect(fetchMock.mock.calls[1]?.[1].headers.get("Authorization")).toBe("Bearer new-token");
  });

  it("preserves unavailable refresh failures and clears only rejected refreshes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    accessTokenStore.replace("token");
    const unavailable = new SameOriginHttpClient();
    unavailable.setRefreshHandler(async () => { throw new ApiUnavailableError(); });
    await expect(unavailable.get("/api/v1/devices")).rejects.toBeInstanceOf(ApiUnavailableError);
    expect(accessTokenStore.read()).toBe("token");

    const rejected = new SameOriginHttpClient();
    rejected.setRefreshHandler(async () => { throw new UnauthenticatedError(); });
    await expect(rejected.get("/api/v1/devices")).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(accessTokenStore.read()).toBeUndefined();
  });

  it("does not refresh a request that remains unauthorized after one retry", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const refresh = vi.fn(async () => { accessTokenStore.replace("rotated"); });
    const client = new SameOriginHttpClient();
    client.setRefreshHandler(refresh);
    await expect(client.get("/api/v1/devices")).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("sends JSON only to same-origin API paths and includes same-origin credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await new SameOriginHttpClient().postJson("/api/v1/auth/refresh", undefined);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/refresh",
      expect.objectContaining({ credentials: "same-origin", method: "POST" })
    );
  });

  it("rejects non-API paths before a request is made", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(new SameOriginHttpClient().get("https://example.invalid/api")).rejects.toThrow(
      "same-origin"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
