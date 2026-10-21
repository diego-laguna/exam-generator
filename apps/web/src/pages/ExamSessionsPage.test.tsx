import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../session";
import { json, stubApi } from "../test-utils";
import { ExamSessionsPage } from "./ExamSessionsPage";
import { SessionDashboardPage } from "./SessionDashboardPage";

const session = (over: object = {}) => ({
  id: 5,
  exam_id: "sample",
  exam_title: "Sample exam",
  question_count: 6,
  duration_minutes: 45,
  started_at: "2026-10-21T10:00:00Z",
  ends_at: "2099-01-01T00:00:00Z",
  status: "open",
  closed_early: false,
  join_url: "http://localhost:5173/join/secret",
  participant_count: 2,
  submitted_count: 1,
  ...over,
});

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/exam" element={<ExamSessionsPage />} />
          <Route path="/sessions/:sessionId" element={<SessionDashboardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken("token");
});

const board = {
  session: session(),
  participants: [
    { id: 1, name: "Ana", status: "submitted", answered_count: 6, score: 5, joined_at: "2026-10-21T10:01:00Z", submitted_at: "2026-10-21T10:20:00Z" },
    { id: 2, name: "Ben", status: "in_progress", answered_count: 2, score: null, joined_at: "2026-10-21T10:02:00Z", submitted_at: null },
  ],
  average_score: 5,
  questions: [{ key: "q1", number: 1, stem: "Which gas?", answered_count: 2, correct_count: 1 }],
  server_now: "2026-10-21T10:21:00Z",
};

describe("exam sessions", () => {
  it("starts a session with the chosen time limit and opens its dashboard", async () => {
    const { calls } = stubApi({
      "GET /api/v1/sample-exam": () =>
        json({ id: "sample", title: "Sample exam", question_count: 6, questions: [] }),
      "GET /api/v1/exam-sessions": () => json([]),
      "POST /api/v1/exam-sessions": () => json(session(), 201),
      "GET /api/v1/exam-sessions/5": () => json(board),
    });
    renderAt("/exam");
    const user = userEvent.setup();
    const minutes = await screen.findByLabelText("Time limit (minutes)");
    await user.clear(minutes);
    await user.type(minutes, "45");
    await user.click(screen.getByRole("button", { name: "Start Exam Session" }));

    const post = calls.find((c) => c.method === "POST");
    expect(await post?.json()).toEqual({ exam_id: "sample", duration_minutes: 45 });
    expect(await screen.findByDisplayValue("http://localhost:5173/join/secret")).toBeInTheDocument();
  });

  it("shows who joined, who submitted and the scores", async () => {
    stubApi({ "GET /api/v1/exam-sessions/5": () => json(board) });
    renderAt("/sessions/5");
    expect(await screen.findByText("Ana")).toBeInTheDocument();
    expect(screen.getByText("5 / 6", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("in progress")).toBeInTheDocument();
    expect(screen.getByText("1 (50%)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End session now" })).toBeInTheDocument();
  });

  it("hides the end button once the session has ended", async () => {
    stubApi({ "GET /api/v1/exam-sessions/5": () => json({ ...board, session: session({ status: "ended", closed_early: true }) }) });
    renderAt("/sessions/5");
    expect(await screen.findByText("ended early")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End session now" })).not.toBeInTheDocument();
  });
});
