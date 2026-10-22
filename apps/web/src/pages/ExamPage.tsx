import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import type { Schema } from "@exam-generator/api-client";

import { ErrorText, StatusBadge } from "../components/Status";
import { ApiError, unwrap } from "../errors";
import { formatClock, useCountdown } from "../format";
import { api } from "../session";

type Exam = Schema["ExamOut"];
type ExamQuestion = Schema["ExamQuestionOut"];
type Feedback = Schema["AnswerOut"];

function Timer({ endsAt, onExpired }: { endsAt: string; onExpired: () => void }) {
  const left = useCountdown(endsAt);
  useEffect(() => {
    if (left === 0) onExpired();
  }, [left, onExpired]);
  if (left === null) return null;
  return (
    <p className={left <= 300 ? "timer warn" : "timer"} role="timer" aria-label="Time left">
      Time left: <strong>{formatClock(left)}</strong> <span className="hint">(the server clock decides)</span>
    </p>
  );
}

function Question({
  question,
  number,
  selected,
  feedback,
  onChoose,
}: {
  question: ExamQuestion;
  number: number;
  selected: string | undefined;
  feedback: Feedback | undefined;
  onChoose: (letter: string) => void;
}) {
  return (
    <section className="card question-take" role="radiogroup" aria-labelledby={`q-${question.id}-stem`}>
      <h3 id={`q-${question.id}-stem`}>
        {number}. {question.stem}
      </h3>
      {Object.entries(question.options)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([letter, text]) => (
          <label key={letter} className="check option">
            <input
              type="radio"
              name={`q-${question.id}`}
              checked={selected === letter}
              onChange={() => onChoose(letter)}
            />
            <strong>{letter}.</strong> {text}
          </label>
        ))}
      {feedback?.is_correct !== undefined ? (
        <div role="status" className={feedback.is_correct ? "feedback right" : "feedback wrong"}>
          <strong>{feedback.is_correct ? "Correct." : `Not quite. The correct answer is ${feedback.correct_option}.`}</strong>{" "}
          {feedback.explanation}
        </div>
      ) : null}
    </section>
  );
}

export function ExamPage() {
  const examId = Number(useParams().examId);
  const queryClient = useQueryClient();
  const queryKey = ["exam", examId];

  const exam = useQuery({
    queryKey,
    queryFn: async () => unwrap(await api.GET("/api/v1/exams/{exam_id}", { params: { path: { exam_id: examId } } })),
    refetchInterval: (query) => (query.state.data?.status === "generating" ? 2000 : false),
  });

  const [selected, setSelected] = useState<Record<number, string>>({});
  const [feedback, setFeedback] = useState<Record<number, Feedback>>({});
  const [saveError, setSaveError] = useState<unknown>(null);

  // Seed the local answers from the server (after a reload, or when the exam starts).
  const questions = exam.data?.questions;
  useEffect(() => {
    if (!questions) return;
    setSelected((current) => {
      const next = { ...current };
      for (const q of questions) if (q.selected_option && !(q.id in next)) next[q.id] = q.selected_option;
      return next;
    });
  }, [questions]);

  const refreshAll = async () => {
    await queryClient.invalidateQueries({ queryKey });
    await queryClient.invalidateQueries({ queryKey: ["exams"] });
    await queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  const start = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/exams/{exam_id}/start", { params: { path: { exam_id: examId } } })),
    onSuccess: async (started) => {
      queryClient.setQueryData(queryKey, started);
      await queryClient.invalidateQueries({ queryKey: ["exams"] });
    },
  });

  const submit = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/exams/{exam_id}/submit", { params: { path: { exam_id: examId } } })),
    onSuccess: refreshAll,
  });

  async function choose(question: ExamQuestion, letter: string) {
    const previous = selected[question.id];
    setSelected((current) => ({ ...current, [question.id]: letter }));
    setSaveError(null);
    try {
      const saved = unwrap(
        await api.PUT("/api/v1/exams/{exam_id}/answers/{question_id}", {
          params: { path: { exam_id: examId, question_id: question.id } },
          body: { selected_option: letter as "A" | "B" | "C" | "D" },
        }),
      );
      setFeedback((current) => ({ ...current, [question.id]: saved }));
    } catch (error) {
      setSelected((current) => {
        const next = { ...current };
        if (previous) next[question.id] = previous;
        else delete next[question.id];
        return next;
      });
      setSaveError(error);
      // The window closed or the exam ended: reload to show the real state.
      if (error instanceof ApiError && error.status === 409) await refreshAll();
    }
  }

  if (exam.isPending) return <p>Loading&hellip;</p>;
  if (exam.error) return <ErrorText error={exam.error} />;
  const current: Exam = exam.data;
  const label = current.mode === "exam" ? "Exam" : "Practice";
  const unanswered = (current.questions ?? []).filter((q) => !selected[q.id]).length;

  return (
    <>
      <div className="row">
        <h1 className="grow">
          {label} #{current.id}
        </h1>
        <StatusBadge status={current.status} />
      </div>
      <p>
        <Link to="/exams">&larr; All sessions</Link>
      </p>

      {current.status === "generating" ? <p aria-live="polite">Preparing your questions&hellip;</p> : null}

      {current.status === "failed" ? (
        <p role="alert" className="alert-error">
          No questions were available for this selection. Try other domains.
        </p>
      ) : null}

      {current.status === "ready" ? (
        <section className="card stack">
          <p>
            {current.question_count} question{current.question_count === 1 ? "" : "s"}
            {current.question_count < current.requested_question_count
              ? ` (you asked for ${current.requested_question_count}; that is all the bank holds for this selection)`
              : ""}
            .{" "}
            {current.duration_minutes
              ? `You will have ${current.duration_minutes} minutes once you start, and the clock cannot be paused.`
              : "There is no time limit."}
          </p>
          <ErrorText error={start.error} />
          <button type="button" onClick={() => start.mutate()} disabled={start.isPending}>
            Start {current.mode === "exam" ? "exam" : "practice"}
          </button>
        </section>
      ) : null}

      {current.status === "in_progress" ? (
        <>
          {current.ends_at ? <Timer endsAt={current.ends_at} onExpired={() => void refreshAll()} /> : null}
          {current.mode === "exam" ? (
            <p className="hint">Answers are saved as you choose them. Feedback appears in the results after you submit.</p>
          ) : null}
          <ErrorText error={saveError} />
          {current.questions?.map((q, index) => (
            <Question
              key={q.id}
              question={q}
              number={index + 1}
              selected={selected[q.id]}
              feedback={feedback[q.id]}
              onChoose={(letter) => void choose(q, letter)}
            />
          ))}
          <section className="card row sticky-bottom">
            <span className="grow">
              {unanswered === 0 ? "All questions answered." : `${unanswered} unanswered.`}
            </span>
            <ErrorText error={submit.error} />
            <button
              type="button"
              disabled={submit.isPending}
              onClick={() =>
                (unanswered === 0 || window.confirm(`${unanswered} question(s) are unanswered. Submit anyway?`)) &&
                submit.mutate()
              }
            >
              Submit {current.mode === "exam" ? "exam" : "session"}
            </button>
          </section>
        </>
      ) : null}

      {current.status === "finished" ? (
        <section className="card stack" aria-live="polite">
          <h2>
            Score: {current.score ?? 0} / {current.question_count}
          </h2>
          <p>
            <Link to={`/exams/${current.id}/results`}>See the answers and explanations</Link>
          </p>
        </section>
      ) : null}
    </>
  );
}
