/** Payloads and responses already exposed by the current anonymous auth HTTP API. */
export interface RegisterRequest {
  email: string;
  password: string;
}

/**
 * Temporary request assumption for the pending login contract. It must be
 * reconciled with the backend before the HTTP adapter is relied on.
 */
export interface ProvisionalLoginRequest {
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

/** Temporary mock-only shape; it is not a server contract. */
export interface ProvisionalDevice {
  readonly name: string;
  readonly platform: string;
  readonly connection: "online" | "offline";
  readonly lastSeen: string;
  readonly agentVersion: string;
}

/** A local mock identity; it is never an authorization assertion. */
export interface MockIdentity {
  readonly kind: "mock";
  readonly displayName: string;
}

/** Successful HTTP operation with an intentionally unparsed pending contract. */
export interface ProvisionalContractResponse {
  readonly kind: "contract-pending";
  readonly operation: "login" | "refresh" | "logout" | "me" | "devices";
  readonly status: number;
}

export type LoginResult = MockIdentity | ProvisionalContractResponse;
export type MeResult = MockIdentity | ProvisionalContractResponse;
export type DeviceListResult =
  | { readonly kind: "mock"; readonly devices: readonly ProvisionalDevice[] }
  | ProvisionalContractResponse;
