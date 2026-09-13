import { SameOriginHttpClient } from "./http";

describe("SameOriginHttpClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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
