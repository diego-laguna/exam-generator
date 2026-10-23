import type { Schema } from "@exam-generator/api-client";

export type FieldError = { field: string; message: string };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly requestId?: string,
    readonly fieldErrors: FieldError[] = [],
  ) {
    super(message);
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const text = (value: unknown): string | undefined => (typeof value === "string" && value ? value : undefined);

/** Turns an RFC 9457 problem body (`ProblemDetail`) into an ApiError; tolerates non-JSON or unknown bodies. */
export function toApiError(status: number, body: unknown): ApiError {
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
  return new ApiError(message, status, text(problem.code), requestId, fieldErrors);
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
