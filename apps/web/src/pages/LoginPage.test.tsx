import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth";
import { setAccessToken } from "../session";
import { fakeToken, json, problem, stubApi } from "../test-utils";
import { LoginPage } from "./LoginPage";

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/documents" element={<p>Documents page</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("LoginPage", () => {
  it("signs in with a form-encoded request and moves on", async () => {
    const { calls } = stubApi({
      "POST /api/v1/auth/refresh": () => problem(401, "UNAUTHORIZED", "no session"),
      "POST /api/v1/auth/login": () => json({ access_token: fakeToken("teacher"), refresh_token: "r", token_type: "bearer" }),
    });
    renderLogin();
    await userEvent.type(await screen.findByLabelText("Username"), "dave");
    await userEvent.type(screen.getByLabelText("Password"), "teacher-pass");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Documents page")).toBeInTheDocument();
    const login = calls.find((c) => c.url.endsWith("/auth/login"));
    expect(login?.headers.get("Content-Type")).toContain("application/x-www-form-urlencoded");
    const form = new URLSearchParams(await login?.text());
    expect(form.get("username")).toBe("dave");
    expect(form.get("password")).toBe("teacher-pass");
  });

  it("shows a clear message for wrong credentials", async () => {
    stubApi({
      "POST /api/v1/auth/refresh": () => problem(401, "UNAUTHORIZED", "no session"),
      "POST /api/v1/auth/login": () => problem(401, "UNAUTHORIZED", "Incorrect username or password"),
    });
    renderLogin();
    await userEvent.type(await screen.findByLabelText("Username"), "dave");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password");
  });

  describe("rate limiting", () => {
    async function failLogin(res: () => Response) {
      stubApi({
        "POST /api/v1/auth/refresh": () => problem(401, "UNAUTHORIZED", "no session"),
        "POST /api/v1/auth/login": res,
      });
      renderLogin();
      await userEvent.type(await screen.findByLabelText("Username"), "dave");
      await userEvent.type(screen.getByLabelText("Password"), "wrong");
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
      return screen.findByRole("alert");
    }
    const limited = (retryAfter?: string) => () => {
      const base = problem(429, "TOO_MANY_REQUESTS", "Too many failed login attempts");
      const headers = new Headers(base.headers);
      if (retryAfter !== undefined) headers.set("Retry-After", retryAfter);
      return new Response(base.body, { status: 429, headers });
    };

    it("shows minutes rounded up from Retry-After", async () => {
      const alert = await failLogin(limited("900"));
      expect(alert).toHaveTextContent("Too many failed attempts. Try again in 15 minutes.");
      expect(alert).not.toHaveTextContent("Incorrect username or password");
    });

    it("shows seconds below a minute", async () => {
      expect(await failLogin(limited("30"))).toHaveTextContent("Try again in 30 seconds.");
    });

    it("falls back to a generic message without the header", async () => {
      expect(await failLogin(limited())).toHaveTextContent("Too many failed attempts. Try again later.");
    });
  });

  it("skips the form when a session can be restored from the cookie", async () => {
    stubApi({ "POST /api/v1/auth/refresh": () => json({ access_token: fakeToken("teacher") }) });
    renderLogin();
    expect(await screen.findByText("Documents page")).toBeInTheDocument();
  });
});
