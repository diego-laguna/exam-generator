import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../session";
import { json, problem, stubApi } from "../test-utils";
import { ResultsPage } from "./ResultsPage";
import { SamplesPage } from "./SamplesPage";
import { UsersPage } from "./UsersPage";

function renderAt(path: string, route: string, element: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  setAccessToken("token");
});

describe("UsersPage", () => {
  it("creates a user with the chosen role and lists it", async () => {
    const { calls } = stubApi({
      "POST /api/v1/users": () => json({ id: 9, username: "maria", role: "teacher", is_active: true, created_at: "x" }, 201),
    });
    renderAt("/users", "/users", <UsersPage />);
    await userEvent.type(screen.getByLabelText("Username"), "maria");
    await userEvent.type(screen.getByLabelText(/Password/), "long-enough-pass");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByText("maria")).toBeInTheDocument();
    expect(await calls.find((c) => c.method === "POST")?.json()).toEqual({
      username: "maria",
      password: "long-enough-pass",
      role: "teacher",
    });
  });

  it("shows the API's message when the username is taken", async () => {
    stubApi({ "POST /api/v1/users": () => problem(409, "USERNAME_TAKEN", "Username already exists") });
    renderAt("/users", "/users", <UsersPage />);
    await userEvent.type(screen.getByLabelText("Username"), "maria");
    await userEvent.type(screen.getByLabelText(/Password/), "long-enough-pass");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Username already exists");
  });
});

describe("SamplesPage", () => {
  const taxonomy = {
    domains: [
      {
        domain_id: 1,
        name: "Design Secure Architectures",
        attempted: 0,
        correct: 0,
        accuracy: null,
        task_statements: [{ code: "1.1", description: "Design secure access", attempted: 0, correct: 0, accuracy: null }],
      },
    ],
  };

  it("rejects bad JSON locally and posts a valid batch", async () => {
    const { calls } = stubApi({
      "GET /api/v1/me/stats": () => json(taxonomy),
      "POST /api/v1/samples": () => json({ created: 1, ids: [3] }, 201),
    });
    renderAt("/samples", "/samples", <SamplesPage />);
    const box = screen.getByLabelText("JSON array");

    await userEvent.type(box, "not json");
    await userEvent.click(screen.getByRole("button", { name: "Add samples" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not valid JSON");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await userEvent.clear(box);
    await userEvent.click(box);
    await userEvent.paste('[{"task_statement":"1.1","stem":"x","options":{},"correct_option":"A"}]');
    await userEvent.click(screen.getByRole("button", { name: "Add samples" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added 1 sample.");
  });

  it("builds a single sample from the form", async () => {
    const { calls } = stubApi({
      "GET /api/v1/me/stats": () => json(taxonomy),
      "POST /api/v1/samples": () => json({ created: 1, ids: [4] }, 201),
    });
    renderAt("/samples", "/samples", <SamplesPage />);
    await screen.findByRole("option", { name: /1\.1 Design secure access/ });
    await userEvent.selectOptions(screen.getByLabelText("Topic"), "t:1.1");
    await userEvent.type(screen.getByLabelText(/^Question/), "Which option is the right one to choose here?");
    for (const [letter, text] of [["A", "one"], ["B", "two"], ["C", "three"], ["D", "four"]] as const) {
      await userEvent.type(screen.getByLabelText(`Option ${letter}`), text);
    }
    await userEvent.selectOptions(screen.getByLabelText("Correct option"), "C");
    await userEvent.click(screen.getByRole("button", { name: "Add sample" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added 1 sample.");
    expect(await calls.find((c) => c.method === "POST")?.json()).toEqual({
      samples: [
        {
          stem: "Which option is the right one to choose here?",
          options: { A: "one", B: "two", C: "three", D: "four" },
          correct_option: "C",
          task_statement: "1.1",
        },
      ],
    });
  });
});

describe("ResultsPage", () => {
  it("explains why results are locked", async () => {
    stubApi({
      "GET /api/v1/exams/5/results": () =>
        problem(409, "RESULTS_LOCKED", "Results unlock after you submit or time runs out"),
    });
    renderAt("/exams/5/results", "/exams/:examId/results", <ResultsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Results unlock after you submit");
  });

  it("marks your answer and the correct one", async () => {
    stubApi({
      "GET /api/v1/exams/5/results": () =>
        json({
          exam_id: 5,
          mode: "exam",
          status: "finished",
          correct: 0,
          answered: 1,
          total: 1,
          percent: 0,
          questions: [
            {
              id: 11,
              position: 1,
              domain: "Design Secure Architectures",
              task_statement: "1.1",
              stem: "Which service stores objects?",
              options: { A: "S3", B: "EC2" },
              selected_option: "B",
              correct_option: "A",
              is_correct: false,
              explanation: "S3 stores objects.",
            },
          ],
        }),
    });
    renderAt("/exams/5/results", "/exams/:examId/results", <ResultsPage />);
    expect(await screen.findByText("0 / 1 correct")).toBeInTheDocument();
    expect(screen.getByText("Incorrect")).toBeInTheDocument();
    expect(screen.getByText("correct answer")).toBeInTheDocument();
    expect(screen.getByText("your answer")).toBeInTheDocument();
  });
});
