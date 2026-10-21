import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { formatClock, formatDateTime, useCountdown } from "../format";
import { api } from "../session";

const REFRESH_MS = 5000;

/** Live results of one session. Polls while the session is open so submissions show up within seconds. */
export function SessionDashboardPage() {
  const sessionId = Number(useParams().sessionId);
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);

  const board = useQuery({
    queryKey: ["exam-sessions", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/exam-sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
    // Keep polling while students can still answer; once ended one last fetch has the final scores.
    refetchInterval: (query) => (query.state.data?.session.status === "ended" ? false : REFRESH_MS),
  });

  const close = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exam-sessions/{session_id}/close", { params: { path: { session_id: sessionId } } }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["exam-sessions"] });
    },
  });

  const secondsLeft = useCountdown(board.data?.session.status === "open" ? board.data.session.ends_at : null);

  if (board.isPending) return <p>Loading&hellip;</p>;
  if (board.error) return <ErrorText error={board.error} />;
  const { session, participants, questions, average_score } = board.data;
  const open = session.status === "open";

  async function copy() {
    try {
      await navigator.clipboard.writeText(session.join_url);
      setCopied(true);
    } catch {
      setCopied(false); // the link is shown in a selectable field below
    }
  }

  return (
    <>
      <h1>{session.exam_title}</h1>
      <section className="card stack" aria-label="Session">
        <div className="row">
          <span className={open ? "badge status-ready" : "badge status-done"}>
            {open ? "open" : session.closed_early ? "ended early" : "ended"}
          </span>
          {open && secondsLeft !== null ? (
            <span className={secondsLeft <= 60 ? "timer warn" : "timer"}>
              Time left: <strong>{formatClock(secondsLeft)}</strong>
            </span>
          ) : (
            <span className="hint">Ended {formatDateTime(session.closed_early ? undefined : session.ends_at)}</span>
          )}
          <span className="grow" />
          {open ? (
            <button
              type="button"
              className="danger"
              disabled={close.isPending}
              onClick={() => window.confirm("End the session now? Students who have not submitted are scored on what they saved.") && close.mutate()}
            >
              End session now
            </button>
          ) : null}
        </div>
        <label>
          Link for students ({session.duration_minutes} minute limit)
          <div className="row">
            <input className="grow" readOnly value={session.join_url} onFocus={(e) => e.currentTarget.select()} />
            <button type="button" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy link"}
            </button>
          </div>
        </label>
        <ErrorText error={close.error} />
      </section>

      <section className="card row" aria-label="Summary">
        <div>
          <strong>{session.participant_count}</strong> <span className="hint">joined</span>
        </div>
        <div>
          <strong>{session.submitted_count}</strong> <span className="hint">submitted</span>
        </div>
        <div>
          <strong>{average_score === null ? "–" : `${average_score} / ${session.question_count}`}</strong>{" "}
          <span className="hint">average score</span>
        </div>
        {open ? <span className="hint grow">Updates every few seconds</span> : null}
      </section>

      <h2>Students</h2>
      {participants.length === 0 ? <p>Nobody has joined yet. Share the link above.</p> : null}
      {participants.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Answered</th>
              <th>Score</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {participants.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.status === "submitted" ? "submitted" : "in progress"}</td>
                <td>
                  {p.answered_count} / {session.question_count}
                </td>
                <td>{p.score === null ? "–" : `${p.score} / ${session.question_count}`}</td>
                <td>{formatDateTime(p.submitted_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <h2>Questions</h2>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Question</th>
            <th>Answered</th>
            <th>Correct</th>
          </tr>
        </thead>
        <tbody>
          {questions.map((q) => (
            <tr key={q.key}>
              <td>{q.number}</td>
              <td>{q.stem}</td>
              <td>{q.answered_count}</td>
              <td>{q.answered_count === 0 ? "–" : `${q.correct_count} (${Math.round((100 * q.correct_count) / q.answered_count)}%)`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
