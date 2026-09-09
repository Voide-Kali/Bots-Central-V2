import type {
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  DeviceListResult,
  LoginResult,
  MeResult,
  ProvisionalLoginRequest,
  RegisterAcceptedResponse,
  RegisterRequest
} from "./contracts";

export interface AuthApi {
  register(input: RegisterRequest): Promise<RegisterAcceptedResponse>;
  consumeVerificationCode(input: ConsumeVerificationCodeRequest): Promise<ConsumeVerificationCodeResponse>;
  login(input: ProvisionalLoginRequest): Promise<LoginResult>;
  refresh(): Promise<MeResult>;
  logout(): Promise<void>;
  me(): Promise<MeResult>;
}

export interface DevicesApi {
  list(): Promise<DeviceListResult>;
}

export interface ApiClient {
  readonly adapterName: "http" | "mock";
  readonly auth: AuthApi;
  readonly devices: DevicesApi;
}
