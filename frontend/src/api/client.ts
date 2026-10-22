import type {
  ActionKind,
  AdminEvent,
  AdminFailure,
  AdminOverview,
  AdminUser,
  AuditEvent,
  AuthenticatedUser,
  ConsumeVerificationCodeRequest,
  ConsumeVerificationCodeResponse,
  Device,
  DeviceTelemetry,
  LoginRequest,
  PairingResponse,
  RegisterAcceptedResponse,
  RegisterRequest,
  StartActionResult,
  TelegramLinkCode,
  TelegramStatus,
  WebActionStatus
} from "./contracts";

export interface AuthApi {
  register(input: RegisterRequest): Promise<RegisterAcceptedResponse>;
  consumeVerificationCode(input: ConsumeVerificationCodeRequest): Promise<ConsumeVerificationCodeResponse>;
  login(input: LoginRequest): Promise<void>;
  refresh(): Promise<void>;
  logout(): Promise<void>;
  me(): Promise<AuthenticatedUser>;
  /** Optional so older fakes keep compiling; asks the server to send a fresh code. */
  resendVerification?(email: string): Promise<void>;
}

export interface DevicesApi {
  list(): Promise<readonly Device[]>;
  createPairing(): Promise<PairingResponse>;
  revokePairing(pairingId: string): Promise<void>;
  approve(id: string, fingerprint: string): Promise<void>;
  reject(id: string, fingerprint: string): Promise<void>;
  /** Samples of the last `minutes` (oldest first). Optional so older fakes keep compiling. */
  history?(id: string, minutes: number): Promise<readonly DeviceTelemetry[]>;
  /** ADR-018: keep this computer reporting every second for the next 60 s. */
  watch?(id: string): Promise<void>;
  /** ADR-021: run a catalogue action from the panel, approved with the PIN. */
  startAction?(id: string, kind: ActionKind, pin: string): Promise<StartActionResult>;
  /** ADR-021: poll a panel-started action until it finishes. */
  actionStatus?(id: string, commandId: string): Promise<WebActionStatus>;
  /** ADR-021: the photo bytes of a finished webcam_photo, handed over once. */
  actionPhoto?(id: string, commandId: string): Promise<Blob>;
}

export interface TelegramApi {
  status(): Promise<TelegramStatus>;
  createLinkCode(): Promise<TelegramLinkCode>;
  unlink(): Promise<void>;
}

export interface AdminApi {
  overview(): Promise<AdminOverview>;
  users(): Promise<readonly AdminUser[]>;
  failures(): Promise<readonly AdminFailure[]>;
  events(): Promise<readonly AdminEvent[]>;
  activate(userId: string): Promise<void>;
}

export interface ActionPinApi {
  status(): Promise<{ readonly configured: boolean; readonly lockedUntil: string | null }>;
  set(password: string, pin: string): Promise<void>;
}

export interface AuditApi {
  list(limit?: number): Promise<readonly AuditEvent[]>;
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
  readonly audit?: AuditApi;
  readonly actionPin?: ActionPinApi;
  readonly admin?: AdminApi;
}
