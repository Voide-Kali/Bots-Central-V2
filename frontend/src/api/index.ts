import type { ApiClient } from "./client";
import { createHttpApiClient } from "./httpAdapter";

export function createApiClient(): ApiClient {
  return createHttpApiClient();
}

export type { ApiClient } from "./client";
export { ApiError, ApiUnavailableError, ForbiddenError, UnauthenticatedError } from "./errors";
