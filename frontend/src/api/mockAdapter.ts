import type { ApiClient, AuthApi, DevicesApi } from "./client";
import type {
  ConsumeVerificationCodeResponse,
  DeviceListResult,
  LoginResult,
  MeResult,
  MockIdentity,
  RegisterAcceptedResponse
} from "./contracts";
import { UnauthenticatedError } from "./errors";

/** Visual-only device fixtures, deliberately limited to the approved MVP fields. */
export const mockDevices = [
  {
    id: "PC000",
    name: "Estação de trabalho",
    platform: "Linux",
    connection: "online" as const,
    lastSeen: "agora",
    agentVersion: "0.1.0"
  },
  {
    id: "MBP-07",
    name: "Laptop de viagem",
    platform: "macOS",
    connection: "offline" as const,
    lastSeen: "há 18 min",
    agentVersion: "0.1.0"
  },
  {
    id: "NODE-02",
    name: "Servidor doméstico",
    platform: "Ubuntu",
    connection: "online" as const,
    lastSeen: "há 4 min",
    agentVersion: "0.1.0"
  }
];

class MockAuthApi implements AuthApi {
  private identity: MockIdentity | undefined;
  public async register(): Promise<RegisterAcceptedResponse> { return { message: "Confira seu e-mail para continuar a verificação." }; }
  public async consumeVerificationCode(): Promise<ConsumeVerificationCodeResponse> { return { verified: true }; }
  public async login(): Promise<LoginResult> {
    this.identity = { kind: "mock", displayName: "Operador de demonstração" };
    return this.identity;
  }
  public async refresh(): Promise<MeResult> { return this.me(); }
  public async logout(): Promise<void> { this.identity = undefined; }
  public async me(): Promise<MeResult> {
    if (this.identity === undefined) throw new UnauthenticatedError();
    return this.identity;
  }
}

class MockDevicesApi implements DevicesApi {
  public async list(): Promise<DeviceListResult> { return { kind: "mock", devices: mockDevices }; }
}

export function createMockApiClient(): ApiClient {
  return { adapterName: "mock", auth: new MockAuthApi(), devices: new MockDevicesApi() };
}
