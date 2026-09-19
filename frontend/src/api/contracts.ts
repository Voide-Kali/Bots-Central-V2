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
