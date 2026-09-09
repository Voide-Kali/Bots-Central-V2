export class ApiError extends Error {
  public constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
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

export class ContractPendingError extends Error {
  public constructor(public readonly operation: string) {
    super(`The ${operation} response contract has not been integrated.`);
    this.name = "ContractPendingError";
  }
}
