import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function ResultsPage() {
  const examId = Number(useParams().examId);
  const results = useQuery({
    queryKey: ["results", examId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/exams/{exam_id}/results", { params: { path: { exam_id: examId } } })),
  });

  if (results.isPending) return <p>Loading&hellip;</p>;
  if (results.error) {
    return (
      <>
        <ErrorText error={results.error} />
        <p>
          <Link to={`/exams/${examId}`}>&larr; Back to the exam</Link>
        </p>
      </>
    );
  }
  const r = results.data;

  return (
    <>
      <h1>
        Results: {r.mode === "exam" ? "Exam" : "Practice"} #{r.exam_id}
      </h1>
      <p>
        <Link to="/exams">&larr; All sessions</Link>
      </p>
      <section className="card">
        <h2>
          {r.correct} / {r.total} correct ({r.percent}%)
        </h2>
        <p className="hint">
          {r.answered} answered
          {r.status !== "finished" ? " so far; only answered questions are shown until the session is finished" : ""}.
        </p>
      </section>

      {r.questions.map((q) => (
        <article key={q.id} className="card question">
          <header className="question-head">
            <span className={q.is_correct ? "badge status-ready" : "badge status-failed"}>
              {q.selected_option === null ? "Unanswered" : q.is_correct ? "Correct" : "Incorrect"}
            </span>
            <span className="hint">
              {q.domain} &middot; {q.task_statement}
            </span>
          </header>
          <h3>
            {q.position}. {q.stem}
          </h3>
          <ul className="options">
            {Object.entries(q.options)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([letter, text]) => {
                const isCorrect = letter === q.correct_option;
                const isYours = letter === q.selected_option;
                return (
                  <li key={letter} className={isCorrect ? "correct" : isYours ? "wrong-pick" : undefined}>
                    <strong>{letter}.</strong> {text}
                    {isCorrect ? <span className="tag"> correct answer</span> : null}
                    {isYours ? <span className="tag"> your answer</span> : null}
                  </li>
                );
              })}
          </ul>
          <p className="explanation">{q.explanation}</p>
        </article>
      ))}
    </>
  );
}
