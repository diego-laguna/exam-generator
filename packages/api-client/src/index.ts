import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };

/** Schema types by name, e.g. `Schema["QuestionOut"]`. */
export type Schema = components["schemas"];

export interface ApiClientOptions {
  /** Base URL of the API, without trailing slash. Empty string means same origin (e.g. a dev proxy). */
  baseUrl?: string;
  /** Called for every request to get the current access token, if any. */
  getAccessToken?: () => string | null | undefined;
  /** Replaces the global fetch, e.g. to retry a request after refreshing the session. */
  fetch?: (request: Request) => Promise<Response>;
}

export function createApiClient({ baseUrl = "", getAccessToken, fetch }: ApiClientOptions = {}) {
  const client = createClient<paths>({ baseUrl, ...(fetch ? { fetch } : {}) });
  if (getAccessToken) {
    const auth: Middleware = {
      onRequest({ request }) {
        const token = getAccessToken();
        if (token) request.headers.set("Authorization", `Bearer ${token}`);
        return request;
      },
    };
    client.use(auth);
  }
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;
