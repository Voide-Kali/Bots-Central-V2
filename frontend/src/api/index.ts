import type { ApiClient } from "./client";
import { createHttpApiClient } from "./httpAdapter";
import { createMockApiClient } from "./mockAdapter";

function selectedAdapter(): "http" | "mock" {
  if (import.meta.env.VITE_API_ADAPTER === "mock") return "mock";
  if (import.meta.env.VITE_API_ADAPTER === "http") return "http";
  return import.meta.env.DEV ? "mock" : "http";
}

export function createApiClient(): ApiClient {
  return selectedAdapter() === "mock" ? createMockApiClient() : createHttpApiClient();
}

export type { ApiClient } from "./client";
export { ApiError, ApiUnavailableError, ContractPendingError, UnauthenticatedError } from "./errors";
