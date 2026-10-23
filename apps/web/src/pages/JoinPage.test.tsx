import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { json, problem, stubApi } from "../test-utils";
import { JoinPage } from "./JoinPage";

const info = {
  exam_title: "Sample exam",
  question_count: 2,
  duration_minutes: 30,
  ends_at: "2099-01-01T00:00:00Z",
  status: "open",
  server_now: "2026-10-21T00:00:00Z",
};
const questions = [
  { key: "q1", type: "mcq", stem: "Which gas?", options: { A: "Oxygen", B: "Carbon dioxide" } },
  { key: "q2", type: "true_false", stem: "Sound is faster than light.", options: { A: "True", B: "False" } },
];
const state = (over: object = {}) => ({
  name: "Ana",
  status: "in_progress",
  ends_at: "2099-01-01T00:00:00Z",
  server_now: "2026-10-21T00:00:00Z",
  questions,
  answers: {},
  result: null,
  ...over,
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/join/abc"]}>
        <Routes>
          <Route path="/join/:token" element={<JoinPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("JoinPage", () => {
  it("lets a student join with a name, answer, submit and see the result", async () => {
    let answers: Record<string, string> = {};
    let result: object | null = null;
    const { calls } = stubApi({
      "GET /api/v1/join/abc": () => json(info),
      "POST /api/v1/join/abc/participants": () => json({ participant_token: "secret-token-123", name: "Ana" }, 201),
      "GET /api/v1/join/abc/me": () => json(state({ answers, result, status: result ? "submitted" : "in_progress", questions: result ? [] : questions })),
      "PUT /api/v1/join/abc/answers/q1": () => {
        answers = { q1: "B" };
        return new Response(null, { status: 204 });
      },
      "POST /api/v1/join/abc/submit": () => {
        result = {
          score: 1,
          total: 2,
          review: [
            { key: "q1", stem: "Which gas?", options: { A: "Oxygen", B: "Carbon dioxide" }, selected_option: "B", correct_option: "B", explanation: "Plants take in CO2.", is_correct: true },
            { key: "q2", stem: "Sound is faster than light.", options: { A: "True", B: "False" }, selected_option: null, correct_option: "B", explanation: "Light is faster.", is_correct: false },
          ],
        };
        return json(result);
      },
    });
    renderPage();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Your name"), "Ana");
    await user.click(screen.getByRole("button", { name: "Start exam" }));

    await user.click(await screen.findByLabelText("B. Carbon dioxide"));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("X-Participant-Token")).toBe("secret-token-123");
    expect(await put?.json()).toEqual({ selected_option: "B" });
    expect(sessionStorage.getItem("participant:abc")).toBe("secret-token-123");

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Submit exam" }));
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("Light is faster.")).toBeInTheDocument();
    expect(screen.getByText("Not answered.")).toBeInTheDocument();
  });

  it("restores a student's exam after a reload from the saved participant token", async () => {
    sessionStorage.setItem("participant:abc", "secret-token-123");
    const { calls } = stubApi({
      "GET /api/v1/join/abc": () => json(info),
      "GET /api/v1/join/abc/me": () => json(state({ answers: { q1: "B" } })),
    });
    renderPage();
    expect(await screen.findByLabelText("B. Carbon dioxide")).toBeChecked();
    expect(screen.queryByLabelText("Your name")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("says so when the session has ended or the link is wrong", async () => {
    stubApi({ "GET /api/v1/join/abc": () => json({ ...info, status: "ended" }) });
    renderPage();
    expect(await screen.findByText("This exam session has ended.")).toBeInTheDocument();

    vi.unstubAllGlobals();
    stubApi({ "GET /api/v1/join/abc": () => problem(404, "NOT_FOUND", "Exam session not found") });
    renderPage();
    expect(await screen.findByText("This exam link is not valid.")).toBeInTheDocument();
  });
});
