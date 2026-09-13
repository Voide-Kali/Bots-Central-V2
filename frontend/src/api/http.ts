import { ApiError, ApiUnavailableError, ForbiddenError, UnauthenticatedError } from "./errors";
import { accessTokenStore } from "./memoryAccessToken";

interface RequestOptions {
  readonly acceptedStatuses?: readonly number[];
  readonly includeAccessToken?: boolean;
}

export class SameOriginHttpClient {
  public async postJson(path: string, body?: unknown, options: RequestOptions = {}): Promise<Response> {
    return this.request(
      path,
      { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) },
      options
    );
  }

  public async get(path: string, options: RequestOptions = {}): Promise<Response> {
    return this.request(path, { method: "GET" }, options);
  }

  private async request(path: string, init: RequestInit, options: RequestOptions): Promise<Response> {
    if (!path.startsWith("/api/")) {
      throw new Error("The web client only permits same-origin API paths.");
    }
    const headers = new Headers(init.headers);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");
    const accessToken = options.includeAccessToken === false ? undefined : accessTokenStore.read();
    if (accessToken !== undefined) headers.set("Authorization", `Bearer ${accessToken}`);

    let response: Response;
    try {
      response = await fetch(path, { ...init, headers, credentials: "same-origin" });
    } catch {
      throw new ApiUnavailableError();
    }
    if (response.status === 401) {
      accessTokenStore.clear();
      throw new UnauthenticatedError();
    }
    if (response.status === 403) throw await forbidden(response);
    if (response.status >= 500) throw new ApiUnavailableError();
    if (!(options.acceptedStatuses ?? [200]).includes(response.status)) {
      throw new ApiError("The API rejected this request.", response.status);
    }
    return response;
  }
}

async function forbidden(response: Response): Promise<ForbiddenError> {
  try {
    const value: unknown = await response.clone().json();
    if (typeof value === "object" && value !== null && "code" in value && typeof value.code === "string") {
      return new ForbiddenError(value.code);
    }
  } catch {
    // A 403 is still meaningful even when an endpoint has no JSON error body.
  }
  return new ForbiddenError();
}

export async function readKnownJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The API returned an invalid response.", response.status);
  }
}
