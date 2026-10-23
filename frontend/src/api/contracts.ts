/** Request and response contracts exposed by the MVP-1 backend. */
export interface RegisterRequest {
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterAcceptedResponse {
  message: string;
}

export interface ConsumeVerificationCodeRequest {
  challenge_id: string;
  code: string;
}

export interface ConsumeVerificationCodeResponse {
  verified: boolean;
}

export interface AuthenticatedUser {
  readonly id: string;
  readonly email: string;
  /** Absent on older servers; only "admin" shows the admin tab (the backend still decides). */
  readonly role?: "user" | "admin";
}

export interface AdminOverview {
  readonly checkedAt: string;
  readonly users: Readonly<Record<string, number>>;
  readonly devicesByLifecycle: Readonly<Record<string, number>>;
  readonly devicesOnline: number;
  readonly commands24h: Readonly<Record<string, number>>;
  readonly telegramLinks: number;
}

export interface AdminUser {
  readonly id: string;
  readonly email: string;
  readonly status: string;
  readonly role: string;
  readonly createdAt: string;
  readonly devices: number;
  readonly telegram: boolean;
  readonly pin: boolean;
}

export interface AdminFailure {
  readonly at: string;
  readonly user: string;
  readonly device: string;
  readonly action: string;
  readonly status: string;
  readonly error: string | null;
}

export interface AdminEvent {
  readonly occurredAt: string;
  readonly user: string | null;
  readonly action: string;
  readonly outcome: string;
}

export type DevicePresence = "online" | "offline";
export type DeviceLifecycleStatus = "pending" | "active" | "revoked";

/** Server-owned metadata; presence is supplied by the backend, never inferred by the UI. */
export interface Device {
  readonly id: string;
  readonly name: string;
  readonly platform: string;
  readonly status: DevicePresence;
  readonly lifecycleStatus: DeviceLifecycleStatus;
  readonly lastSeenAt: string | null;
  readonly agentVersion: string | null;
  readonly fingerprint: string | null;
  readonly telemetry: DeviceTelemetry | null;
}

/** Latest system metrics accepted with a signed heartbeat (ADR-012). Null fields were not reported. */
export interface DeviceTelemetry {
  readonly recordedAt: string;
  readonly cpuPercent: number | null;
  readonly load1: number | null;
  readonly cpuCount: number | null;
  readonly memoryTotalBytes: number | null;
  readonly memoryUsedBytes: number | null;
  readonly diskTotalBytes: number | null;
  readonly diskUsedBytes: number | null;
  readonly temperatureC: number | null;
  readonly uptimeSeconds: number | null;
}

export interface PairingResponse {
  readonly pairingId: string;
  readonly pairingToken: string;
  readonly expiresAt: string;
}

export interface EnrollmentResponse {
  readonly deviceId: string;
  readonly lifecycleStatus: "pending";
  readonly fingerprint: string;
}

export interface TelegramLinkCode {
  readonly code: string;
  readonly expiresAt: string;
  readonly botUsername: string | null;
}

export interface TelegramStatus {
  readonly linked: boolean;
  readonly botUsername: string | null;
}

export interface AuditEvent {
  readonly occurredAt: string;
  readonly actor: string;
  readonly action: string;
  readonly outcome: string;
  readonly name: string | null;
}
