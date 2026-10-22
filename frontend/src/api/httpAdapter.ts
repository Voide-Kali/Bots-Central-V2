import type { ActionPinApi, ApiClient, AuditApi, AuthApi, DevicesApi, PasswordResetApi, TelegramApi } from "./client";
import type {
  AuditEvent,
  AuthenticatedUser,
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  Device,
  DeviceTelemetry,
  PairingResponse,
  LoginRequest,
  RegisterAcceptedResponse,
  RegisterRequest,
  TelegramLinkCode,
  TelegramStatus
} from "./contracts";
import { ApiError } from "./errors";
import { SameOriginHttpClient, readKnownJson } from "./http";
import { accessTokenStore } from "./memoryAccessToken";

const paths = {
  register: "/api/v1/auth/register",
  resend: "/api/v1/auth/email-verification/resend",
  consumeCode: "/api/v1/auth/email-verification/consume-code",
  login: "/api/v1/auth/login",
  refresh: "/api/v1/auth/refresh",
  logout: "/api/v1/auth/logout",
  me: "/api/v1/auth/me",
  devices: "/api/v1/devices",
  telegramLink: "/api/v1/telegram/link",
  telegramLinkCode: "/api/v1/telegram/link-code",
  resetRequest: "/api/v1/auth/password-reset/request",
  resetConfirm: "/api/v1/auth/password-reset/confirm",
  audit: "/api/v1/audit",
  actionPin: "/api/v1/me/action-pin"
} as const;

const botUsernamePattern = /^[A-Za-z0-9_]{5,32}$/;

function assertBotUsername(value: unknown, status: number): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !botUsernamePattern.test(value)) throw new ApiError("The API returned an invalid response.", status);
  return value;
}

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

const telemetryNumberKeys = [
  ["cpu_percent", "cpuPercent"],
  ["load1", "load1"],
  ["cpu_count", "cpuCount"],
  ["memory_total_bytes", "memoryTotalBytes"],
  ["memory_used_bytes", "memoryUsedBytes"],
  ["disk_total_bytes", "diskTotalBytes"],
  ["disk_used_bytes", "diskUsedBytes"],
  ["temperature_c", "temperatureC"],
  ["uptime_seconds", "uptimeSeconds"]
] as const;

function assertTelemetry(value: unknown, status: number): DeviceTelemetry | null {
  if (value === undefined || value === null) return null;
  if (!isRecord(value) || typeof value.recorded_at !== "string" || !Number.isFinite(Date.parse(value.recorded_at))) {
    throw new ApiError("The API returned an invalid response.", status);
  }
  const result: Record<string, number | null | string> = { recordedAt: value.recorded_at };
  for (const [wire, field] of telemetryNumberKeys) {
    const item = value[wire];
    if (item !== null && (typeof item !== "number" || !Number.isFinite(item))) {
      throw new ApiError("The API returned an invalid response.", status);
    }
    result[field] = item;
  }
  return result as unknown as DeviceTelemetry;
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
    fingerprint: value.fingerprint,
    telemetry: assertTelemetry(value.telemetry, status)
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

  public async resendVerification(email: string): Promise<void> {
    await this.http.postJson(paths.resend, { email }, { acceptedStatuses: [202], includeAccessToken: false });
  }

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

class HttpTelegramApi implements TelegramApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async status(): Promise<TelegramStatus> {
    const response = await this.http.get(paths.telegramLink, { acceptedStatuses: [200] });
    const value = await readKnownJson<unknown>(response);
    if (!isRecord(value) || typeof value.linked !== "boolean") throw new ApiError("The API returned an invalid response.", response.status);
    return { linked: value.linked, botUsername: assertBotUsername(value.bot_username, response.status) };
  }

  public async createLinkCode(): Promise<TelegramLinkCode> {
    const response = await this.http.postJson(paths.telegramLinkCode, {}, { acceptedStatuses: [201] });
    const value = await readKnownJson<unknown>(response);
    if (!isRecord(value) || typeof value.code !== "string" || !/^[23456789ABCDEFGHJKMNPQRSTVWXYZ]{10}$/.test(value.code) || typeof value.expires_at !== "string" || !Number.isFinite(Date.parse(value.expires_at))) {
      throw new ApiError("The API returned an invalid response.", response.status);
    }
    return { code: value.code, expiresAt: value.expires_at, botUsername: assertBotUsername(value.bot_username, response.status) };
  }

  public async unlink(): Promise<void> {
    await this.http.delete(paths.telegramLink, { acceptedStatuses: [204] });
  }
}

class HttpPasswordResetApi implements PasswordResetApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async request(email: string): Promise<void> {
    await this.http.postJson(paths.resetRequest, { email }, { acceptedStatuses: [202], includeAccessToken: false });
  }

  public async confirm(input: { readonly email: string; readonly code: string; readonly newPassword: string }): Promise<void> {
    await this.http.postJson(paths.resetConfirm, { email: input.email, code: input.code, new_password: input.newPassword }, { acceptedStatuses: [200], includeAccessToken: false });
  }
}

const MAX_AUDIT_ITEMS = 100; // backend MAX_LIST

function parseAuditEvent(value: unknown, status: number): AuditEvent {
  if (!isRecord(value) || typeof value.occurred_at !== "string" || !Number.isFinite(Date.parse(value.occurred_at)) || typeof value.actor !== "string" || typeof value.action !== "string" || typeof value.outcome !== "string") {
    throw new ApiError("The API returned an invalid response.", status);
  }
  const details = value.details;
  const name = isRecord(details) && typeof details.name === "string" ? details.name.slice(0, 120) : null;
  return { occurredAt: value.occurred_at, actor: value.actor, action: value.action, outcome: value.outcome, name };
}

class HttpAuditApi implements AuditApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async list(limit = 50): Promise<readonly AuditEvent[]> {
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_AUDIT_ITEMS) throw new RangeError("limit out of range");
    const response = await this.http.get(`${paths.audit}?limit=${limit}`, { acceptedStatuses: [200] });
    const value = await readKnownJson<unknown>(response);
    if (!isRecord(value) || !Array.isArray(value.events) || value.events.length > MAX_AUDIT_ITEMS) throw new ApiError("The API returned an invalid response.", response.status);
    return value.events.map((item) => parseAuditEvent(item, response.status));
  }
}

class HttpActionPinApi implements ActionPinApi {
  public constructor(private readonly http: SameOriginHttpClient) {}

  public async status(): Promise<{ readonly configured: boolean; readonly lockedUntil: string | null }> {
    const response = await this.http.get(paths.actionPin, { acceptedStatuses: [200] });
    const value = await readKnownJson<unknown>(response);
    if (!isRecord(value) || typeof value.configured !== "boolean" || (value.locked_until !== null && typeof value.locked_until !== "string")) {
      throw new ApiError("The API returned an invalid response.", response.status);
    }
    return { configured: value.configured, lockedUntil: value.locked_until as string | null };
  }

  public async set(password: string, pin: string): Promise<void> {
    await this.http.putJson(paths.actionPin, { password, pin }, { acceptedStatuses: [204] });
  }
}

export function createHttpApiClient(): ApiClient {
  const http = new SameOriginHttpClient();
  const auth = new HttpAuthApi(http);
  http.setRefreshHandler(() => auth.refresh());
  return { auth, devices: new HttpDevicesApi(http), telegram: new HttpTelegramApi(http), passwordReset: new HttpPasswordResetApi(http), audit: new HttpAuditApi(http), actionPin: new HttpActionPinApi(http) };
}
