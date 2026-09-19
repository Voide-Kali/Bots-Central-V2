import type { ApiClient, AuthApi, DevicesApi } from "./client";
import type {
  AuthenticatedUser,
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  Device,
  PairingResponse,
  LoginRequest,
  RegisterAcceptedResponse,
  RegisterRequest
} from "./contracts";
import { ApiError } from "./errors";
import { SameOriginHttpClient, readKnownJson } from "./http";
import { accessTokenStore } from "./memoryAccessToken";

const paths = {
  register: "/api/v1/auth/register",
  consumeCode: "/api/v1/auth/email-verification/consume-code",
  login: "/api/v1/auth/login",
  refresh: "/api/v1/auth/refresh",
  logout: "/api/v1/auth/logout",
  me: "/api/v1/auth/me",
  devices: "/api/v1/devices"
} as const;

// Refresh rotation is single-use. This is module-scoped so a Strict Mode effect replay
// cannot accidentally redeem the same HttpOnly cookie twice.
let refreshInFlight: Promise<void> | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function assertMessage(value: unknown, status: number): RegisterAcceptedResponse {
  if (isRecord(value) && typeof value.message === "string") return { message: value.message };
  throw new ApiError("The API returned an invalid response.", status);
}

function assertVerificationResult(value: unknown, status: number): ConsumeVerificationCodeResponse {
  if (isRecord(value) && typeof value.verified === "boolean") return { verified: value.verified };
  throw new ApiError("The API returned an invalid response.", status);
}

function assertAccessTokenResponse(value: unknown, status: number): string {
  if (!isRecord(value)
    || typeof value.access_token !== "string" || value.access_token.length === 0
    || value.token_type !== "Bearer" || typeof value.expires_in !== "number") {
    throw new ApiError("The API returned an invalid response.", status);
  }
  return value.access_token;
}

function assertUser(value: unknown, status: number): AuthenticatedUser {
  if (!isRecord(value)
    || typeof value.id !== "string" || value.id.length === 0
    || typeof value.email !== "string" || value.email.length === 0) {
    throw new ApiError("The API returned an invalid response.", status);
  }
  return { id: value.id, email: value.email };
}

function assertDevice(value: unknown, status: number): Device {
  if (!isRecord(value)
    || typeof value.id !== "string" || typeof value.name !== "string" || typeof value.platform !== "string"
    || (value.status !== "online" && value.status !== "offline")
    || (value.lifecycle_status !== "pending" && value.lifecycle_status !== "active" && value.lifecycle_status !== "revoked")
    || (value.last_seen_at !== null && typeof value.last_seen_at !== "string")
    || (value.agent_version !== null && typeof value.agent_version !== "string")
    || (value.fingerprint !== null && typeof value.fingerprint !== "string")) {
    throw new ApiError("The API returned an invalid response.", status);
  }
  return {
    id: value.id,
    name: value.name,
    platform: value.platform,
    status: value.status,
    lifecycleStatus: value.lifecycle_status,
    lastSeenAt: value.last_seen_at,
    agentVersion: value.agent_version,
    fingerprint: value.fingerprint
  };
}

function assertPairing(value: unknown, status: number): PairingResponse {
  if (!isRecord(value) || typeof value.pairing_id !== "string" || typeof value.pairing_token !== "string" || typeof value.expires_at !== "string" || !Number.isFinite(Date.parse(value.expires_at)) || value.pairing_id.length === 0 || value.pairing_token.length === 0) {
    throw new ApiError("The API returned an invalid response.", status);
  }
  return { pairingId: value.pairing_id, pairingToken: value.pairing_token, expiresAt: value.expires_at };
}

function assertDevices(value: unknown, status: number): readonly Device[] {
  if (!isRecord(value) || !Array.isArray(value.devices)) {
    throw new ApiError("The API returned an invalid response.", status);
  }
  return value.devices.map((device) => assertDevice(device, status));
}

class HttpAuthApi implements AuthApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async register(input: RegisterRequest): Promise<RegisterAcceptedResponse> {
    const response = await this.http.postJson(paths.register, input, { acceptedStatuses: [202], includeAccessToken: false });
    return assertMessage(await readKnownJson<unknown>(response), response.status);
  }

  public async consumeVerificationCode(input: ConsumeVerificationCodeRequest): Promise<ConsumeVerificationCodeResponse> {
    const response = await this.http.postJson(paths.consumeCode, input, { acceptedStatuses: [200, 400], includeAccessToken: false });
    return assertVerificationResult(await readKnownJson<unknown>(response), response.status);
  }

  public async login(input: LoginRequest): Promise<void> {
    const response = await this.http.postJson(paths.login, input, { acceptedStatuses: [200], includeAccessToken: false });
    accessTokenStore.replace(assertAccessTokenResponse(await readKnownJson<unknown>(response), response.status));
  }

  public refresh(): Promise<void> {
    if (refreshInFlight !== undefined) return refreshInFlight;
    const request = this.refreshOnce();
    refreshInFlight = request;
    void request.then(
      () => { if (refreshInFlight === request) refreshInFlight = undefined; },
      () => { if (refreshInFlight === request) refreshInFlight = undefined; }
    );
    return request;
  }

  private async refreshOnce(): Promise<void> {
    const response = await this.http.postJson(paths.refresh, undefined, { acceptedStatuses: [200], includeAccessToken: false });
    accessTokenStore.replace(assertAccessTokenResponse(await readKnownJson<unknown>(response), response.status));
  }

  public async logout(): Promise<void> {
    try {
      await this.http.postJson(paths.logout, undefined, { acceptedStatuses: [200, 202, 204] });
    } finally {
      accessTokenStore.clear();
    }
  }

  public async me(): Promise<AuthenticatedUser> {
    const response = await this.http.get(paths.me, { acceptedStatuses: [200] });
    return assertUser(await readKnownJson<unknown>(response), response.status);
  }
}

class HttpDevicesApi implements DevicesApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async list(): Promise<readonly Device[]> {
    const response = await this.http.get(paths.devices, { acceptedStatuses: [200] });
    return assertDevices(await readKnownJson<unknown>(response), response.status);
  }

  public async createPairing(): Promise<PairingResponse> {
    const response = await this.http.postJson(`${paths.devices}/pairings`, {}, { acceptedStatuses: [201] });
    return assertPairing(await readKnownJson<unknown>(response), response.status);
  }

  public async revokePairing(pairingId: string): Promise<void> {
    await this.http.delete(`${paths.devices}/pairings/${encodeURIComponent(pairingId)}`, { acceptedStatuses: [204] });
  }

  public async approve(id: string, fingerprint: string): Promise<void> {
    await this.http.postJson(`${paths.devices}/${encodeURIComponent(id)}/approve`, { fingerprint });
  }

  public async reject(id: string, fingerprint: string): Promise<void> {
    await this.http.postJson(`${paths.devices}/${encodeURIComponent(id)}/reject`, { fingerprint });
  }
}

export function createHttpApiClient(): ApiClient {
  const http = new SameOriginHttpClient();
  const auth = new HttpAuthApi(http);
  http.setRefreshHandler(() => auth.refresh());
  return { auth, devices: new HttpDevicesApi(http) };
}
