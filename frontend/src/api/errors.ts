export class ApiError extends Error {
  public constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

/** A valid session may be forbidden from a resource or device operation. */
export class ForbiddenError extends ApiError {
  public constructor(public readonly code: string | undefined = undefined) {
    super("The API rejected this request.", 403);
    this.name = "ForbiddenError";
  }
}

export class ApiUnavailableError extends Error {
  public constructor() {
    super("The API is temporarily unavailable.");
    this.name = "ApiUnavailableError";
  }
}

export class UnauthenticatedError extends Error {
  public constructor() {
    super("Authentication is required.");
    this.name = "UnauthenticatedError";
  }
}
