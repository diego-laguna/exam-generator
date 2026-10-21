import { createApiClient } from "@exam-generator/api-client";

/**
 * For students who join an exam session from a link. They have no account, so this client never sends
 * an access token or tries to refresh one; the join token in the URL and the participant token header
 * are the only credentials.
 */
// The fetch wrapper looks up the global at call time, so tests can stub it after import.
export const publicApi = createApiClient({ baseUrl: window.location.origin, fetch: (request) => fetch(request) });

const key = (joinToken: string) => `participant:${joinToken}`;

/** The participant secret survives a reload (sessionStorage); storage can be unavailable, so never throw. */
export function loadParticipantToken(joinToken: string): string | null {
  try {
    return sessionStorage.getItem(key(joinToken));
  } catch {
    return null;
  }
}

export function saveParticipantToken(joinToken: string, secret: string) {
  try {
    sessionStorage.setItem(key(joinToken), secret);
  } catch {
    // Without storage a reload asks for the name again, which the server rejects as taken.
  }
}
