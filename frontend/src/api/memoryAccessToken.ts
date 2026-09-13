/** The only permitted access-token location; it is lost when the page reloads. */
class MemoryAccessTokenStore {
  private token: string | undefined;

  public read(): string | undefined {
    return this.token;
  }

  /** Reserved for a future, validated login/refresh contract. */
  public replace(nextToken: string): void {
    this.token = nextToken;
  }

  public clear(): void {
    this.token = undefined;
  }
}

export const accessTokenStore = new MemoryAccessTokenStore();
