import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/Page";
import { ErrorText, StatusBadge } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function GeneratePage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number[]>([]);
  const [mcq, setMcq] = useState(5);
  const [trueFalse, setTrueFalse] = useState(0);
  const [focus, setFocus] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: async () => unwrap(await api.GET("/api/v1/documents")),
  });
  const ready = documents.data?.filter((d) => d.status === "ready") ?? [];

  const job = useQuery({
    queryKey: ["generation", jobId],
    enabled: jobId !== null,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/generations/{job_id}", { params: { path: { job_id: jobId ?? 0 } } })),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : 2000;
    },
  });

  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/generations", {
          body: {
            document_ids: selected,
            mcq_count: mcq,
            true_false_count: trueFalse,
            focus: focus.trim() || null,
          },
        }),
      ),
    onSuccess: (created) => {
      setJobId(created.id);
      void queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
  });

  const toggle = (id: number) =>
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  const running = job.data?.status === "queued" || job.data?.status === "running";
  const total = mcq + trueFalse;

  return (
    <>
      <PageHeader
        title="Generate questions"
        subtitle="Pick documents and how many questions you want. Every question is checked against its citation before it is kept."
      />
      <form onSubmit={submit} className="card stack">
        <fieldset>
          <legend>Documents</legend>
          {ready.length === 0 ? (
            <p className="hint">
              No ready documents. <Link to="/documents">Upload a PDF</Link> and wait until it is ready.
            </p>
          ) : null}
          <div className="choice-grid">
            {ready.map((d) => (
              <label key={d.id} className="check choice">
                <input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} />
                <span className="grow">
                  {d.filename}
                  <span className="choice-meta">{d.page_count ? `${d.page_count} pages` : `${d.chunk_count} chunks`}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="row">
          <label>
            Multiple choice
            <input type="number" min={0} max={50} value={mcq} onChange={(e) => setMcq(Number(e.target.value))} />
          </label>
          <label>
            True / false
            <input
              type="number"
              min={0}
              max={50}
              value={trueFalse}
              onChange={(e) => setTrueFalse(Number(e.target.value))}
            />
          </label>
          <label className="grow">
            Focus (optional)
            <input value={focus} maxLength={500} onChange={(e) => setFocus(e.target.value)} placeholder="e.g. photosynthesis" />
          </label>
        </div>
        <ErrorText error={start.error} />
        <div className="form-footer">
          <span className="hint grow">
            {selected.length} document{selected.length === 1 ? "" : "s"} selected · up to 50 questions per run
          </span>
          <button type="submit" disabled={selected.length === 0 || total < 1 || total > 50 || start.isPending || running}>
            Generate {total} question{total === 1 ? "" : "s"}
          </button>
        </div>
      </form>

      {job.data ? (
        <section className="card stack" aria-live="polite">
          <div className="row">
            <strong className="grow">
              {job.data.produced_count} of {job.data.requested_count} questions produced
            </strong>
            <StatusBadge status={job.data.status} />
          </div>
          <div className="progress-track" aria-hidden="true">
            <div
              className={job.data.status === "failed" ? "progress-fill low" : "progress-fill"}
              style={{ width: `${Math.round((100 * job.data.produced_count) / Math.max(1, job.data.requested_count))}%` }}
            />
          </div>
          {job.data.error ? <p className="alert-error">{job.data.error}</p> : null}
          {job.data.status === "done" ? (
            <p>
              Questions that fail the citation or validation checks are discarded, so fewer than requested is normal.{" "}
              <Link to="/questions">Review the questions</Link>
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
