import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { ErrorText, StatusBadge } from "../components/Status";
import { unwrap } from "../errors";
import { formatDateTime } from "../format";
import { api } from "../session";

export function ExamsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"practice" | "exam">("practice");
  const [count, setCount] = useState("");
  const [domains, setDomains] = useState<number[]>([]);

  const exams = useQuery({
    queryKey: ["exams"],
    queryFn: async () => unwrap(await api.GET("/api/v1/exams")),
  });
  // The stats endpoint lists the exam domains.
  const taxonomy = useQuery({
    queryKey: ["stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/stats")),
  });

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams", {
          body: {
            mode,
            question_count: count ? Number(count) : null,
            domains: domains.length > 0 ? domains : null,
          },
        }),
      ),
    onSuccess: async (exam) => {
      await queryClient.invalidateQueries({ queryKey: ["exams"] });
      navigate(`/exams/${exam.id}`);
    },
  });

  const toggle = (id: number) =>
    setDomains((current) => (current.includes(id) ? current.filter((d) => d !== id) : [...current, id]));

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <>
      <h1>Exams</h1>
      <form onSubmit={submit} className="card stack">
        <h2>New session</h2>
        <fieldset>
          <legend>Mode</legend>
          <label className="check">
            <input type="radio" name="mode" checked={mode === "practice"} onChange={() => setMode("practice")} />
            Practice: no time limit, feedback after each answer
          </label>
          <label className="check">
            <input type="radio" name="mode" checked={mode === "exam"} onChange={() => setMode("exam")} />
            Exam: timed (2 minutes per question), results after you submit or time runs out
          </label>
        </fieldset>
        <label>
          Number of questions (optional, default {mode === "exam" ? 65 : 10})
          <input type="number" min={1} max={100} value={count} onChange={(e) => setCount(e.target.value)} />
        </label>
        <fieldset>
          <legend>Domains (none selected means all)</legend>
          {taxonomy.data?.domains.map((d) => (
            <label key={d.domain_id} className="check">
              <input type="checkbox" checked={domains.includes(d.domain_id)} onChange={() => toggle(d.domain_id)} />
              {d.domain_id}. {d.name}
            </label>
          ))}
        </fieldset>
        <ErrorText error={create.error} />
        <button type="submit" disabled={create.isPending}>
          Create {mode === "exam" ? "exam" : "practice session"}
        </button>
      </form>

      <h2>Your sessions</h2>
      <ErrorText error={exams.error} />
      {exams.data?.length === 0 ? <p>Nothing yet. Create a session above.</p> : null}
      <ul className="list">
        {exams.data?.map((e) => (
          <li key={e.id} className="card row">
            <div className="grow">
              <Link to={`/exams/${e.id}`}>
                <strong>
                  {e.mode === "exam" ? "Exam" : "Practice"} #{e.id}
                </strong>
              </Link>
              <div className="hint">
                {e.question_count} question{e.question_count === 1 ? "" : "s"}
                {e.question_count < e.requested_question_count ? ` (${e.requested_question_count} requested)` : ""}
                {" · "}
                {formatDateTime(e.created_at)}
              </div>
            </div>
            {e.status === "finished" && e.score !== null ? (
              <span>
                {e.score} / {e.question_count}
              </span>
            ) : null}
            <StatusBadge status={e.status} />
            {e.status === "finished" ? <Link to={`/exams/${e.id}/results`}>Results</Link> : null}
          </li>
        ))}
      </ul>
    </>
  );
}
