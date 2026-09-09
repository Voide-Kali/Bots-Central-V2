import type { ApiClient, AuthApi, DevicesApi } from "./client";
import type {
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  DeviceListResult,
  LoginResult,
  MeResult,
  ProvisionalContractResponse,
  ProvisionalLoginRequest,
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

function assertMessage(value: unknown, status: number): RegisterAcceptedResponse {
  if (typeof value === "object" && value !== null && "message" in value && typeof value.message === "string") {
    return { message: value.message };
  }
  throw new ApiError("The API returned an invalid response.", status);
}

function assertVerificationResult(value: unknown, status: number): ConsumeVerificationCodeResponse {
  if (typeof value === "object" && value !== null && "verified" in value && typeof value.verified === "boolean") {
    return { verified: value.verified };
  }
  throw new ApiError("The API returned an invalid response.", status);
}

function contractPending(operation: ProvisionalContractResponse["operation"], status: number): ProvisionalContractResponse {
  return { kind: "contract-pending", operation, status };
}

class HttpAuthApi implements AuthApi {
  private readonly http = new SameOriginHttpClient();

  public async register(input: RegisterRequest): Promise<RegisterAcceptedResponse> {
    const response = await this.http.postJson(paths.register, input, { acceptedStatuses: [202] });
    return assertMessage(await readKnownJson<unknown>(response), response.status);
  }

  public async consumeVerificationCode(input: ConsumeVerificationCodeRequest): Promise<ConsumeVerificationCodeResponse> {
    const response = await this.http.postJson(paths.consumeCode, input, { acceptedStatuses: [200, 400] });
    return assertVerificationResult(await readKnownJson<unknown>(response), response.status);
  }

  public async login(input: ProvisionalLoginRequest): Promise<LoginResult> {
    const response = await this.http.postJson(paths.login, input, { acceptedStatuses: [200, 201, 202, 204] });
    return contractPending("login", response.status);
  }

  public async refresh(): Promise<MeResult> {
    const response = await this.http.postJson(paths.refresh, undefined, { acceptedStatuses: [200, 204] });
    return contractPending("refresh", response.status);
  }

  public async logout(): Promise<void> {
    try {
      await this.http.postJson(paths.logout, undefined, { acceptedStatuses: [200, 202, 204] });
    } finally {
      accessTokenStore.clear();
    }
  }

  public async me(): Promise<MeResult> {
    const response = await this.http.get(paths.me, { acceptedStatuses: [200] });
    return contractPending("me", response.status);
  }
}

class HttpDevicesApi implements DevicesApi {
  private readonly http = new SameOriginHttpClient();

  public async list(): Promise<DeviceListResult> {
    const response = await this.http.get(paths.devices, { acceptedStatuses: [200] });
    return contractPending("devices", response.status);
  }
}

export function createHttpApiClient(): ApiClient {
  return { adapterName: "http", auth: new HttpAuthApi(), devices: new HttpDevicesApi() };
}
