import { vi } from "vitest";

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** An RFC 9457 error response like the API's, with an optional list of field errors. */
export const problem = (
  status: number,
  code: string,
  detail: string,
  errors: { field: string; message: string; type?: string }[] = [],
  requestId = "req-test",
) =>
  new Response(
    JSON.stringify({
      type: "about:blank",
      title: "Error",
      status,
      code,
      detail,
      instance: "/api/v1/test",
      request_id: requestId,
      errors: errors.map((e) => ({ type: "value_error", ...e })),
    }),
    { status, headers: { "Content-Type": "application/problem+json" } },
  );

/** An unsigned JWT-shaped token; the app only reads the role claim, the API verifies the signature. */
export const fakeToken = (role: string) => ["h", btoa(JSON.stringify({ role })), "s"].join(".");

export type Handler = (request: Request) => Response | Promise<Response>;

/** Replaces fetch with a router keyed by "METHOD /path". Unknown routes fail the test loudly. */
export function stubApi(routes: Record<string, Handler>) {
  const calls: Request[] = [];
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(String(input), window.location.origin), init);
    calls.push(request.clone());
    const key = `${request.method} ${new URL(request.url).pathname}`;
    const handler = routes[key];
    if (!handler) throw new Error(`Unexpected request: ${key}`);
    return handler(request);
  });
  vi.stubGlobal("fetch", fetchStub);
  return { calls, fetchStub };
}
