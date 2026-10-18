import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AuthProvider } from "./auth";
import { setAccessToken } from "./session";
import { fakeToken, json, stubApi } from "./test-utils";

function renderApp(path: string, role: string | null) {
  stubApi({
    "POST /api/v1/auth/refresh": () => (role ? json({ access_token: fakeToken(role) }) : json({}, 401)),
    "GET /api/v1/health": () => json({ status: "ok" }),
    "GET /api/v1/documents": () => json([]),
    "GET /api/v1/exams": () => json([]),
    "GET /api/v1/sources": () => json([]),
    "GET /api/v1/me/stats": () => json({ domains: [] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const navLinks = () => within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link").map((l) => l.textContent);

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("role based navigation", () => {
  it("teachers get the teaching screens, sources and stats", async () => {
    renderApp("/", "teacher");
    expect(await screen.findByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(navLinks()).toEqual(["Documents", "Generate", "Questions", "Sets", "Sources", "My stats"]);
  });

  it("students start on their exams", async () => {
    renderApp("/", "student");
    expect(await screen.findByRole("heading", { name: "Exams" })).toBeInTheDocument();
    expect(navLinks()).toEqual(["Exams", "Sources", "My stats"]);
  });

  it("admins get user, sample and source management", async () => {
    renderApp("/", "admin");
    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(navLinks()).toEqual(["Users", "Samples", "Sources", "My stats"]);
  });

  it("explains instead of showing a screen the role cannot use", async () => {
    renderApp("/exams", "teacher");
    expect(await screen.findByRole("heading", { name: "Not available" })).toBeInTheDocument();
    expect(screen.getByText(/not available for your account type \(teacher\)/)).toBeInTheDocument();
  });

  it("sends anonymous visitors to the sign-in page", async () => {
    renderApp("/documents", null);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows whether the API is reachable", async () => {
    renderApp("/", "teacher");
    expect(await screen.findByText("API online")).toBeInTheDocument();
  });

  it("only offers source management to admins", async () => {
    renderApp("/sources", "student");
    expect(await screen.findByRole("heading", { name: "Documentation sources" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add source" })).not.toBeInTheDocument();
  });
});
