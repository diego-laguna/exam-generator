import { describe, expect, it } from "vitest";

import { toApiError, unwrap } from "./errors";

describe("toApiError", () => {
  it("handles string, validation-list and coded details", () => {
    expect(toApiError(404, { detail: "Document not found" }).message).toBe("Document not found");
    expect(toApiError(422, { detail: [{ loc: ["body", "mcq_count"], msg: "must be at least 0" }] }).message).toBe(
      "mcq_count: must be at least 0",
    );
    const coded = toApiError(409, { detail: { code: "JOB_IN_PROGRESS", message: "A generation is already running" } });
    expect(coded.message).toBe("A generation is already running");
    expect(coded.code).toBe("JOB_IN_PROGRESS");
    expect(coded.status).toBe(409);
  });

  it("falls back to a generic message", () => {
    expect(toApiError(500, undefined).message).toBe("Request failed (500)");
  });
});

describe("unwrap", () => {
  it("returns data and throws ApiError otherwise", () => {
    expect(unwrap({ data: [1], response: new Response() })).toEqual([1]);
    expect(() => unwrap({ error: { detail: "nope" }, response: new Response(null, { status: 403 }) })).toThrow("nope");
  });
});
