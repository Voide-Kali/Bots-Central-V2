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
