import type { Schema } from "@exam-generator/api-client";

export type FieldError = { field: string; message: string };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly requestId?: string,
    readonly fieldErrors: FieldError[] = [],
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const text = (value: unknown): string | undefined => (typeof value === "string" && value ? value : undefined);

/** Turns an RFC 9457 problem body (`ProblemDetail`) into an ApiError; tolerates non-JSON or unknown bodies. */
export function toApiError(status: number, body: unknown, response?: Response): ApiError {
  const problem: Partial<Schema["ProblemDetail"]> = isObject(body) ? body : {};
  const fieldErrors: FieldError[] = Array.isArray(problem.errors)
    ? problem.errors.flatMap((e) =>
        isObject(e) && typeof e.message === "string" ? [{ field: text(e.field) ?? "", message: e.message }] : [],
      )
    : [];
  const first = fieldErrors[0];
  const requestId = text(problem.request_id);
  let message =
    (first && `${first.field ? `${first.field}: ` : ""}${first.message}`) ??
    text(problem.detail) ??
    text(problem.title) ??
    `Request failed (${status})`;
  if (status >= 500 && requestId) message += ` (ref ${requestId})`;
  return new ApiError(message, status, text(problem.code), requestId, fieldErrors, parseRetryAfter(response));
}

/** `Retry-After` as whole seconds; undefined when missing or not a non-negative integer (HTTP dates are ignored). */
function parseRetryAfter(response?: Response): number | undefined {
  const raw = response?.headers.get("Retry-After")?.trim();
  return raw && /^\d+$/.test(raw) ? Number(raw) : undefined;
}

/** User-facing text for a rate-limited login; wait times of a minute or more are rounded up to minutes. */
export function tooManyAttemptsMessage(retryAfterSeconds?: number): string {
  const base = "Too many failed attempts.";
  if (retryAfterSeconds === undefined) return `${base} Try again later.`;
  if (retryAfterSeconds >= 60) {
    const minutes = Math.ceil(retryAfterSeconds / 60);
    return `${base} Try again in ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`;
  }
  return `${base} Try again in ${retryAfterSeconds} ${retryAfterSeconds === 1 ? "second" : "seconds"}.`;
}

/** Unwraps an openapi-fetch result: returns the data or throws an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    throw toApiError(result.response.status, result.error, result.response);
  }
  return result.data;
}

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "Something went wrong";
