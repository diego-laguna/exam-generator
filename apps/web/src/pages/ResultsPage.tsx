import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../components/Page";
import { ErrorText, StatusBadge } from "../components/Status";
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
      <PageHeader
        title={`Results: ${r.mode === "exam" ? "Exam" : "Practice"} #${r.exam_id}`}
        back={{ to: "/exams", label: "All sessions" }}
      />
      <section className="card score-hero">
        <strong className="score-number">{r.percent}%</strong>
        <span className="score-sub">
          <strong>
            {r.correct} / {r.total} correct
          </strong>{" "}
          &middot; {r.answered} answered
          {r.status !== "finished" ? " so far; only answered questions are shown until the session is finished" : ""}
        </span>
      </section>

      {r.questions.map((q) => (
        <article key={q.id} className="card question">
          <header className="question-head">
            {q.selected_option === null ? (
              <span className="badge">Unanswered</span>
            ) : (
              <StatusBadge status={q.is_correct ? "ready" : "failed"} label={q.is_correct ? "Correct" : "Incorrect"} />
            )}
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
                    {isCorrect ? <span className="tag correct">correct answer</span> : null}
                    {isYours ? <span className="tag yours">your answer</span> : null}
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
