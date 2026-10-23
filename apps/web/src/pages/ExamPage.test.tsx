import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../session";
import { json, problem, stubApi } from "../test-utils";
import { ExamPage } from "./ExamPage";

const base = {
  id: 5,
  mode: "practice",
  question_count: 2,
  requested_question_count: 2,
  duration_minutes: null,
  started_at: null,
  ends_at: null,
  submitted_at: null,
  score: null,
};
const questions = [
  { id: 11, position: 1, stem: "Which service stores objects?", options: { A: "S3", B: "EC2", C: "VPC", D: "IAM" }, selected_option: null },
  { id: 12, position: 2, stem: "Which service runs VMs?", options: { A: "S3", B: "EC2", C: "VPC", D: "IAM" }, selected_option: null },
];

function renderExam() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/exams/5"]}>
        <Routes>
          <Route path="/exams/:examId" element={<ExamPage />} />
          <Route path="/exams" element={<p>Exam list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken("token");
});

describe("ExamPage", () => {
  it("practice: start, answer with immediate feedback, submit, see the score", async () => {
    let state: Record<string, unknown> = { ...base, status: "ready" };
    const { calls } = stubApi({
      "GET /api/v1/exams/5": () => json(state),
      "POST /api/v1/exams/5/start": () => {
        state = { ...base, status: "in_progress", started_at: "2026-10-18T10:00:00Z", questions };
        return json(state);
      },
      "PUT /api/v1/exams/5/answers/11": () =>
        json({ question_id: 11, selected_option: "B", answered_at: "x", is_correct: false, correct_option: "A", explanation: "S3 stores objects." }),
      "POST /api/v1/exams/5/submit": () => {
        state = { ...base, status: "finished", score: 0 };
        return json(state);
      },
      "GET /api/v1/exams": () => json([]),
      "GET /api/v1/me/stats": () => json({ domains: [] }),
    });
    renderExam();

    expect(await screen.findByText(/There is no time limit/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start practice" }));

    const first = (await screen.findByText(/Which service stores objects\?/)).closest("[role=radiogroup]") as HTMLElement;
    await userEvent.click(within(first).getByLabelText(/B\. EC2/));
    expect(await within(first).findByText(/The correct answer is A/)).toBeInTheDocument();
    expect(within(first).getByText("S3 stores objects.")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT");
    expect(await put?.json()).toEqual({ selected_option: "B" });
    expect(screen.getByText("1 unanswered.")).toBeInTheDocument();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Submit session" }));
    expect(await screen.findByRole("heading", { name: "Score: 0 / 2" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /answers and explanations/ })).toHaveAttribute("href", "/exams/5/results");
  });

  it("exam mode: shows the countdown and no feedback while answering", async () => {
    const endsAt = new Date(Date.now() + 90 * 60_000).toISOString();
    stubApi({
      "GET /api/v1/exams/5": () =>
        json({ ...base, mode: "exam", status: "in_progress", duration_minutes: 4, started_at: "x", ends_at: endsAt, questions }),
      "PUT /api/v1/exams/5/answers/11": () => json({ question_id: 11, selected_option: "A", answered_at: "x" }),
    });
    renderExam();
    expect(await screen.findByRole("timer")).toHaveTextContent(/Time left: 1:(29|30):\d\d/);
    const first = screen.getByText(/Which service stores objects\?/).closest("[role=radiogroup]") as HTMLElement;
    await userEvent.click(within(first).getByLabelText(/A\. S3/));
    expect(within(first).getByLabelText(/A\. S3/)).toBeChecked();
    expect(within(first).queryByRole("status")).not.toBeInTheDocument();
  });

  it("restores saved answers after a reload and reports a closed window", async () => {
    stubApi({
      "GET /api/v1/exams/5": () =>
        json({ ...base, status: "in_progress", started_at: "x", questions: [{ ...questions[0], selected_option: "C" }, questions[1]] }),
      "PUT /api/v1/exams/5/answers/12": () =>
        problem(409, "EXAM_WINDOW_CLOSED", "The exam time has expired"),
      "GET /api/v1/exams": () => json([]),
      "GET /api/v1/me/stats": () => json({ domains: [] }),
    });
    renderExam();
    const first = (await screen.findByText(/Which service stores objects\?/)).closest("[role=radiogroup]") as HTMLElement;
    expect(within(first).getByLabelText(/C\. VPC/)).toBeChecked();

    const second = screen.getByText(/Which service runs VMs\?/).closest("[role=radiogroup]") as HTMLElement;
    await userEvent.click(within(second).getByLabelText(/B\. EC2/));
    expect(await screen.findByRole("alert")).toHaveTextContent("The exam time has expired");
    expect(within(second).getByLabelText(/B\. EC2/)).not.toBeChecked();
  });

  it("explains an empty selection", async () => {
    stubApi({ "GET /api/v1/exams/5": () => json({ ...base, status: "failed", question_count: 0 }) });
    renderExam();
    expect(await screen.findByRole("alert")).toHaveTextContent("No questions were available");
  });
});
