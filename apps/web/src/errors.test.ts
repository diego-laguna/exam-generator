import { describe, expect, it } from "vitest";

import { ApiError, toApiError, unwrap } from "./errors";

const body = (over: object) => ({ type: "about:blank", title: "Error", status: 400, errors: [], ...over });

describe("toApiError", () => {
  it("uses the first field error as 'field: message'", () => {
    const error = toApiError(
      422,
      body({
        code: "VALIDATION_ERROR",
        detail: "Request validation failed",
        errors: [
          { field: "mcq_count", message: "must be at least 0", type: "greater_than_equal" },
          { field: "url", message: "bad", type: "value_error" },
        ],
      }),
    );
    expect(error.message).toBe("mcq_count: must be at least 0");
    expect(error.fieldErrors).toEqual([
      { field: "mcq_count", message: "must be at least 0" },
      { field: "url", message: "bad" },
    ]);
    expect(error.code).toBe("VALIDATION_ERROR");
  });

  it("uses detail, then title, and extracts code and request id", () => {
    const error = toApiError(409, body({ code: "JOB_IN_PROGRESS", detail: "A generation is already running", request_id: "7f3c" }));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("A generation is already running");
    expect(error.code).toBe("JOB_IN_PROGRESS");
    expect(error.requestId).toBe("7f3c");
    expect(error.status).toBe(409);
    expect(toApiError(404, body({ title: "Not Found" })).message).toBe("Not Found");
  });

  it("adds the request id to server errors", () => {
    expect(toApiError(500, body({ detail: "Internal error", request_id: "7f3c" })).message).toBe("Internal error (ref 7f3c)");
  });

  it("falls back for non-JSON or unknown bodies", () => {
    expect(toApiError(502, "<html>Bad Gateway</html>").message).toBe("Request failed (502)");
    expect(toApiError(500, undefined).message).toBe("Request failed (500)");
    expect(toApiError(400, { detail: [{ msg: "old" }] }).message).toBe("Request failed (400)");
  });
});

describe("unwrap", () => {
  it("returns data and throws ApiError otherwise", () => {
    expect(unwrap({ data: [1], response: new Response() })).toEqual([1]);
    expect(() => unwrap({ error: body({ detail: "nope" }), response: new Response(null, { status: 403 }) })).toThrow("nope");
  });
});
