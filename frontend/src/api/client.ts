import type {
  AuthenticatedUser,
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  Device,
  LoginRequest,
  PairingResponse,
  RegisterAcceptedResponse,
  RegisterRequest,
  TelegramLinkCode,
  TelegramStatus
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
  revokePairing(pairingId: string): Promise<void>;
  approve(id: string, fingerprint: string): Promise<void>;
  reject(id: string, fingerprint: string): Promise<void>;
}

export interface TelegramApi {
  status(): Promise<TelegramStatus>;
  createLinkCode(): Promise<TelegramLinkCode>;
  unlink(): Promise<void>;
}

export interface PasswordResetApi {
  request(email: string): Promise<void>;
  confirm(input: { readonly email: string; readonly code: string; readonly newPassword: string }): Promise<void>;
}

export interface ApiClient {
  readonly auth: AuthApi;
  readonly devices: DevicesApi;
  /** Optional so test fakes and older builds keep working without the Telegram card. */
  readonly telegram?: TelegramApi;
  readonly passwordReset?: PasswordResetApi;
}
