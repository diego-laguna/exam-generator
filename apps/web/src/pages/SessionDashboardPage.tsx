import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { EmptyState, PageHeader, Stat } from "../components/Page";
import { ErrorText, StatusBadge } from "../components/Status";
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
      <PageHeader
        title={session.exam_title}
        back={{ to: "/exam", label: "Exam" }}
        subtitle={`Started ${formatDateTime(session.started_at)} · ${session.duration_minutes} minute limit`}
        actions={
          open ? (
            <button
              type="button"
              className="danger"
              disabled={close.isPending}
              onClick={() => window.confirm("End the session now? Students who have not submitted are scored on what they saved.") && close.mutate()}
            >
              End session now
            </button>
          ) : null
        }
      />
      <section className="card stack" aria-label="Session">
        <div className="row">
          <StatusBadge status={session.status} label={open ? undefined : session.closed_early ? "Ended early" : undefined} />
          {open && secondsLeft !== null ? (
            <span className={secondsLeft <= 60 ? "timer warn" : "timer"}>
              Time left: <strong>{formatClock(secondsLeft)}</strong>
            </span>
          ) : (
            <span className="hint">Ended {formatDateTime(session.closed_early ? undefined : session.ends_at)}</span>
          )}
          {open ? <span className="hint live">Updates every few seconds</span> : null}
        </div>
        <label>
          Link for students
          <div className="row">
            <input className="grow" readOnly value={session.join_url} onFocus={(e) => e.currentTarget.select()} />
            <button type="button" className="secondary" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy link"}
            </button>
          </div>
        </label>
        <ErrorText error={close.error} />
      </section>

      <section className="stat-grid" aria-label="Summary">
        <Stat label="Joined" value={session.participant_count} />
        <Stat label="Submitted" value={session.submitted_count} />
        <Stat
          label="Average score"
          value={average_score === null ? "–" : `${average_score} / ${session.question_count}`}
        />
      </section>

      <h2 className="section-title">Students</h2>
      {participants.length === 0 ? (
        <EmptyState icon="👥" title="Nobody has joined yet">
          Share the link above.
        </EmptyState>
      ) : null}
      {participants.length > 0 ? (
        <div className="card table-card">
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
                  <td>
                    <strong>{p.name}</strong>
                  </td>
                  <td>
                    <StatusBadge status={p.status === "submitted" ? "submitted" : "in_progress"} />
                  </td>
                  <td>
                    {p.answered_count} / {session.question_count}
                  </td>
                  <td>{p.score === null ? "–" : `${p.score} / ${session.question_count}`}</td>
                  <td className="hint">{formatDateTime(p.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <h2 className="section-title">Questions</h2>
      <div className="card table-card">
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
            {questions.map((q) => {
              const share = q.answered_count === 0 ? null : q.correct_count / q.answered_count;
              return (
                <tr key={q.key}>
                  <td className="hint">{q.number}</td>
                  <td>{q.stem}</td>
                  <td>{q.answered_count}</td>
                  <td className="cell-bar">
                    {share === null ? (
                      "–"
                    ) : (
                      <>
                        <span className="progress-track" aria-hidden="true">
                          <span
                            className={`progress-fill ${share >= 0.75 ? "" : share >= 0.5 ? "mid" : "low"}`}
                            style={{ width: `${Math.round(100 * share)}%` }}
                          />
                        </span>
                        <span>{`${q.correct_count} (${Math.round(100 * share)}%)`}</span>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
