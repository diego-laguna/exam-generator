import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../session";
import { json, stubApi } from "../test-utils";
import { QuestionsPage } from "./QuestionsPage";

const question = (id: number, stem: string, type: "mcq" | "true_false" = "mcq") => ({
  id,
  type,
  document_id: 1,
  stem,
  options: type === "mcq" ? { A: "Sunlight", B: "Soil", C: "Wind", D: "Salt" } : { A: "True", B: "False" },
  correct_option: "A",
  explanation: "The excerpt says chlorophyll absorbs sunlight.",
  citations: [
    { document: "lesson.pdf", chunk_id: 7, page: 1, line_start: 2, line_end: 3, quote: "Chlorophyll absorbs sunlight" },
  ],
  created_at: "2026-10-18T00:00:00Z",
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/questions"]}>
        <Routes>
          <Route path="/questions" element={<QuestionsPage />} />
          <Route path="/sets/:setId" element={<p>Set page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken("token");
});

describe("QuestionsPage", () => {
  it("shows the answer, explanation and the page/line source of each question", async () => {
    stubApi({
      "GET /api/v1/documents": () => json([]),
      "GET /api/v1/questions": () => json([question(1, "What does chlorophyll absorb?")]),
    });
    renderPage();
    const card = (await screen.findByText("What does chlorophyll absorb?")).closest("article") as HTMLElement;
    expect(within(card).getByText("lesson.pdf, page 1, lines 2–3")).toBeInTheDocument();
    expect(within(card).getByText("Chlorophyll absorbs sunlight")).toBeInTheDocument();
    expect(within(card).getByText("The excerpt says chlorophyll absorbs sunlight.")).toBeInTheDocument();
    expect(within(card).getByText("(correct answer)")).toBeInTheDocument();
  });

  it("saves the selected questions, in selection order, as a named set", async () => {
    const { calls } = stubApi({
      "GET /api/v1/documents": () => json([]),
      "GET /api/v1/questions": () => json([question(1, "First question"), question(2, "Second question", "true_false")]),
      "POST /api/v1/question-sets": () => json({ id: 9, title: "Unit 1 quiz", question_count: 2, questions: [] }, 201),
    });
    renderPage();
    const second = (await screen.findByText("Second question")).closest("article") as HTMLElement;
    const first = screen.getByText("First question").closest("article") as HTMLElement;
    await userEvent.click(within(second).getByLabelText("Select"));
    await userEvent.click(within(first).getByLabelText("Select"));
    await userEvent.type(screen.getByLabelText("Set title"), "Unit 1 quiz");
    await userEvent.click(screen.getByRole("button", { name: "Save as set" }));

    expect(await screen.findByText("Set page")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/question-sets"));
    expect(await post?.json()).toEqual({ title: "Unit 1 quiz", question_ids: [2, 1] });
  });

  it("points to the generator when there are no questions", async () => {
    stubApi({ "GET /api/v1/documents": () => json([]), "GET /api/v1/questions": () => json([]) });
    renderPage();
    expect(await screen.findByText(/No questions yet/)).toBeInTheDocument();
  });
});
