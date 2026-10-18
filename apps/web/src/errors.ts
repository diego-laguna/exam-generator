export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

/** Turns a FastAPI error body into a readable message and, when present, its error code. */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return new ApiError(detail, status);
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
    const field = first?.loc?.filter((p) => p !== "body").join(".");
    return new ApiError(first?.msg ? `${field ? `${field}: ` : ""}${first.msg}` : "Invalid request", status);
  }
  if (detail && typeof detail === "object") {
    const { code, message } = detail as { code?: string; message?: string };
    return new ApiError(message ?? "Request failed", status, code);
  }
  return new ApiError(`Request failed (${status})`, status);
}

/** Unwraps an openapi-fetch result: returns the data or throws an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    throw toApiError(result.response.status, result.error);
  }
  return result.data;
}

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "Something went wrong";
