import type {
  AuthenticatedUser,
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  Device,
  LoginRequest,
  PairingResponse,
  RegisterAcceptedResponse,
  RegisterRequest
} from "./contracts";

export interface AuthApi {
  register(input: RegisterRequest): Promise<RegisterAcceptedResponse>;
  consumeVerificationCode(input: ConsumeVerificationCodeRequest): Promise<ConsumeVerificationCodeResponse>;
  login(input: LoginRequest): Promise<void>;
  refresh(): Promise<void>;
  logout(): Promise<void>;
  me(): Promise<AuthenticatedUser>;
}

export interface DevicesApi {
  list(): Promise<readonly Device[]>;
  createPairing(): Promise<PairingResponse>;
  approve(id: string, fingerprint: string): Promise<void>;
  reject(id: string, fingerprint: string): Promise<void>;
}

export interface ApiClient {
  readonly auth: AuthApi;
  readonly devices: DevicesApi;
}
