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

const demoDevices = [
  { name: "Oficina Sul", platform: "Windows 11", connection: "online" as const, lastSeen: "Agora", agentVersion: "0.1.0-demo" },
  { name: "Notebook de campo", platform: "Ubuntu 24.04", connection: "offline" as const, lastSeen: "Há 2 horas", agentVersion: "0.1.0-demo" }
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
  public async list(): Promise<DeviceListResult> { return { kind: "mock", devices: demoDevices }; }
}

export function createMockApiClient(): ApiClient {
  return { adapterName: "mock", auth: new MockAuthApi(), devices: new MockDevicesApi() };
}
