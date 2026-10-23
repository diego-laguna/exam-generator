import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeToken, json, problem, stubApi } from "./test-utils";

const url = (path: string) => new URL(path, window.location.origin).toString();

async function loadSession() {
  vi.resetModules(); // fresh module state: token and in-flight refresh
  return import("./session");
}

beforeEach(() => {
  vi.unstubAllGlobals();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authFetch", () => {
  it("passes successful responses through without refreshing", async () => {
    const { authFetch } = await loadSession();
    const { calls } = stubApi({ "GET /api/v1/documents": () => json([]) });
    const response = await authFetch(new Request(url("/api/v1/documents")));
    expect(response.status).toBe(200);
    expect(calls).toHaveLength(1);
  });

  it("refreshes once on 401 and retries with the new access token", async () => {
    const { authFetch, getAccessToken } = await loadSession();
    const fresh = fakeToken("teacher");
    let attempts = 0;
    const { calls } = stubApi({
      "GET /api/v1/documents": (request) => {
        attempts += 1;
        return request.headers.get("Authorization") === `Bearer ${fresh}` ? json(["ok"]) : json({}, 401);
      },
      "POST /api/v1/auth/refresh": () => json({ access_token: fresh }),
    });
    const response = await authFetch(new Request(url("/api/v1/documents"), { headers: { Authorization: "Bearer old" } }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(["ok"]);
    expect(attempts).toBe(2);
    expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
    expect(getAccessToken()).toBe(fresh);
  });

  it("shares one refresh between concurrent 401s (refresh tokens are single-use)", async () => {
    const { authFetch } = await loadSession();
    const fresh = fakeToken("teacher");
    const { calls } = stubApi({
      "GET /api/v1/documents": (request) =>
        request.headers.get("Authorization") === `Bearer ${fresh}` ? json([]) : json({}, 401),
      "GET /api/v1/questions": (request) =>
        request.headers.get("Authorization") === `Bearer ${fresh}` ? json([]) : json({}, 401),
      "POST /api/v1/auth/refresh": async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        return json({ access_token: fresh });
      },
    });
    const responses = await Promise.all([
      authFetch(new Request(url("/api/v1/documents"))),
      authFetch(new Request(url("/api/v1/questions"))),
    ]);
    expect(responses.map((r) => r.status)).toEqual([200, 200]);
    expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("clears the token and announces an expired session when the refresh fails", async () => {
    const { authFetch, setAccessToken, getAccessToken, onSessionExpired } = await loadSession();
    setAccessToken("stale");
    const expired = vi.fn();
    onSessionExpired(expired);
    stubApi({
      "GET /api/v1/documents": () => json({}, 401),
      "POST /api/v1/auth/refresh": () => problem(401, "UNAUTHORIZED", "Invalid or expired refresh token"),
    });
    const response = await authFetch(new Request(url("/api/v1/documents")));
    expect(response.status).toBe(401);
    expect(getAccessToken()).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it("does not try to refresh when an auth endpoint itself answers 401", async () => {
    const { authFetch } = await loadSession();
    const { calls } = stubApi({ "POST /api/v1/auth/login": () => problem(401, "UNAUTHORIZED", "no") });
    const response = await authFetch(new Request(url("/api/v1/auth/login"), { method: "POST" }));
    expect(response.status).toBe(401);
    expect(calls).toHaveLength(1);
  });
});

describe("roleFromToken", () => {
  it("reads the role claim and tolerates garbage", async () => {
    const { roleFromToken } = await loadSession();
    expect(roleFromToken(fakeToken("teacher"))).toBe("teacher");
    expect(roleFromToken("not-a-token")).toBeNull();
    expect(roleFromToken("a.%%%.c")).toBeNull();
  });
});
