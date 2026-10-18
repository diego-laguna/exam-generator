import { createApiClient } from "@learn-assistant/api-client";

/**
 * Session handling. The access token lives only in memory; the refresh token is an httpOnly cookie
 * the browser sends to /api/v1/auth, so page scripts never see it. After a reload we get a new
 * access token by calling /auth/refresh.
 */

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
const expiredListeners = new Set<() => void>();

export const getAccessToken = () => accessToken;
export const setAccessToken = (token: string | null) => {
  accessToken = token;
};

export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener);
  return () => expiredListeners.delete(listener);
}

/** One refresh at a time: refresh tokens are single-use, so concurrent callers must share a call. */
export function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch("/api/v1/auth/refresh", { method: "POST" });
      if (!response.ok) {
        accessToken = null;
        return null;
      }
      const body = (await response.json()) as { access_token: string };
      accessToken = body.access_token;
      return accessToken;
    } catch {
      accessToken = null;
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/** The role claim, for showing or hiding screens only. The server enforces authorization. */
export function roleFromToken(token: string): string | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const role = (JSON.parse(json) as { role?: unknown }).role;
    return typeof role === "string" ? role : null;
  } catch {
    return null;
  }
}

/** Retries a request once with a fresh access token when the API answers 401. */
export async function authFetch(request: Request): Promise<Response> {
  const retry = request.clone();
  const response = await fetch(request);
  if (response.status !== 401 || new URL(request.url).pathname.startsWith("/api/v1/auth/")) {
    return response;
  }
  const token = await refreshAccessToken();
  if (!token) {
    expiredListeners.forEach((listener) => listener());
    return response;
  }
  retry.headers.set("Authorization", `Bearer ${token}`);
  return fetch(retry);
}

export const api = createApiClient({
  baseUrl: window.location.origin,
  getAccessToken,
  fetch: authFetch,
});
