import { accessTokenStore } from "./memoryAccessToken";

describe("MemoryAccessTokenStore", () => {
  afterEach(() => { accessTokenStore.clear(); vi.restoreAllMocks(); });

  it("keeps an access token only until explicitly cleared", () => {
    const persist = vi.spyOn(Storage.prototype, "setItem");
    accessTokenStore.replace("ephemeral-access-token");
    expect(accessTokenStore.read()).toBe("ephemeral-access-token");
    expect(persist).not.toHaveBeenCalled();
    accessTokenStore.clear();
    expect(accessTokenStore.read()).toBeUndefined();
  });
});
