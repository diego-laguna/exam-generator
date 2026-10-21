import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { QuestionCard } from "../components/QuestionCard";
import { ErrorText } from "../components/Status";
import { saveBlob } from "../download";
import { unwrap } from "../errors";
import { api } from "../session";

export function SetDetailPage() {
  const setId = Number(useParams().setId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState<string | null>(null);

  const set = useQuery({
    queryKey: ["sets", setId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/question-sets/{set_id}", { params: { path: { set_id: setId } } })),
  });

  const replace = useMutation({
    mutationFn: async (body: { title: string; question_ids: number[] }) =>
      unwrap(await api.PUT("/api/v1/question-sets/{set_id}", { params: { path: { set_id: setId } }, body })),
    onSuccess: async (updated) => {
      queryClient.setQueryData(["sets", setId], updated);
      setTitle(null);
      await queryClient.invalidateQueries({ queryKey: ["sets"] });
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.DELETE("/api/v1/question-sets/{set_id}", {
        params: { path: { set_id: setId } },
      });
      if (error !== undefined) unwrap({ error, response });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sets"] });
      navigate("/sets");
    },
  });

  const download = useMutation({
    mutationFn: async (version: "student" | "teacher") => {
      const { data, error, response } = await api.GET("/api/v1/question-sets/{set_id}/pdf", {
        params: { path: { set_id: setId }, query: { version } },
        parseAs: "blob",
      });
      if (error !== undefined || !data) unwrap({ error, response });
      saveBlob(data as Blob, `${set.data?.title ?? "questions"}-${version}.pdf`);
    },
  });

  if (set.isPending) return <p>Loading&hellip;</p>;
  if (set.error) return <ErrorText error={set.error} />;
  const current = set.data;
  const ids = current.questions.map((q) => q.id);

  function rename(event: FormEvent) {
    event.preventDefault();
    if (title?.trim()) replace.mutate({ title: title.trim(), question_ids: ids });
  }

  return (
    <>
      <h1>{current.title}</h1>
      <div className="card row">
        <button type="button" onClick={() => download.mutate("student")} disabled={download.isPending}>
          Download student PDF
        </button>
        <button type="button" onClick={() => download.mutate("teacher")} disabled={download.isPending}>
          Download answer key
        </button>
        <span className="grow" />
        <button
          type="button"
          className="danger"
          onClick={() => window.confirm(`Delete the set "${current.title}"? Its questions are kept.`) && remove.mutate()}
        >
          Delete set
        </button>
      </div>
      <form onSubmit={rename} className="row">
        <label className="grow">
          Rename
          <input value={title ?? current.title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <button type="submit" disabled={title === null || !title.trim() || replace.isPending}>
          Save name
        </button>
      </form>
      <ErrorText error={download.error ?? replace.error ?? remove.error} />

      {current.questions.map((q, index) => (
        <QuestionCard
          key={q.id}
          question={q}
          number={index + 1}
          actions={
            <button
              type="button"
              className="danger"
              disabled={ids.length === 1 || replace.isPending}
              title={ids.length === 1 ? "A set needs at least one question" : undefined}
              onClick={() =>
                replace.mutate({ title: current.title, question_ids: ids.filter((id) => id !== q.id) })
              }
            >
              Remove from set
            </button>
          }
        />
      ))}
    </>
  );
}
