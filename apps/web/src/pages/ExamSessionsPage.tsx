import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { saveBlob } from "../download";
import { unwrap } from "../errors";
import { formatDateTime } from "../format";
import { api } from "../session";
import { ErrorText, StatusBadge } from "../components/Status";

/** The built-in exam: download it as PDFs or open a timed session for students. */
export function ExamSessionsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [minutes, setMinutes] = useState(30);

  const exam = useQuery({
    queryKey: ["sample-exam"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sample-exam")),
  });
  const sessions = useQuery({
    queryKey: ["exam-sessions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/exam-sessions")),
  });

  const download = useMutation({
    mutationFn: async (version: "student" | "teacher") => {
      const { data, error, response } = await api.GET("/api/v1/sample-exam/pdf", {
        params: { query: { version } },
        parseAs: "blob",
      });
      if (error !== undefined || !data) unwrap({ error, response });
      saveBlob(data as Blob, `sample-exam-${version}.pdf`);
    },
  });

  const start = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/exam-sessions", { body: { exam_id: "sample", duration_minutes: minutes } })),
    onSuccess: async (session) => {
      await queryClient.invalidateQueries({ queryKey: ["exam-sessions"] });
      navigate(`/sessions/${session.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  return (
    <>
      <h1>Exam</h1>
      {exam.isPending ? <p>Loading&hellip;</p> : null}
      <ErrorText error={exam.error} />
      {exam.data ? (
        <section className="card stack" aria-label="Exam">
          <h2>{exam.data.title}</h2>
          <p className="hint">
            {exam.data.question_count} questions (multiple choice and true/false). This is a built-in exam.
          </p>
          <div className="row">
            <button type="button" onClick={() => download.mutate("student")} disabled={download.isPending}>
              Download student PDF
            </button>
            <button type="button" onClick={() => download.mutate("teacher")} disabled={download.isPending}>
              Download answer key
            </button>
          </div>
          <ErrorText error={download.error} />
          <details>
            <summary>Preview the questions</summary>
            <ol>
              {exam.data.questions.map((q) => (
                <li key={q.key}>
                  {q.stem} <span className="hint">(answer {q.correct_option})</span>
                </li>
              ))}
            </ol>
          </details>
        </section>
      ) : null}

      <form className="card stack" onSubmit={submit} aria-label="Start exam session">
        <h2>Start exam session</h2>
        <p className="hint">
          Students open the link you get, enter a name and answer. The time limit starts now and cannot be changed
          afterwards; you can end the session early.
        </p>
        <div className="row">
          <label>
            Time limit (minutes)
            <input
              type="number"
              min={1}
              max={480}
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
            />
          </label>
          <button type="submit" disabled={start.isPending || !(minutes >= 1)}>
            Start Exam Session
          </button>
        </div>
        <ErrorText error={start.error} />
      </form>

      <h2>Sessions</h2>
      <ErrorText error={sessions.error} />
      {sessions.data?.length === 0 ? <p>No sessions yet.</p> : null}
      <ul className="list">
        {sessions.data?.map((s) => (
          <li key={s.id} className="card row">
            <Link to={`/sessions/${s.id}`} className="grow">
              <strong>{s.exam_title}</strong> &middot; {formatDateTime(s.started_at)}
            </Link>
            <span className="hint">
              {s.submitted_count}/{s.participant_count} submitted &middot; {s.duration_minutes} min
            </span>
            <StatusBadge status={s.status === "open" ? "ready" : "done"} />
          </li>
        ))}
      </ul>
    </>
  );
}
