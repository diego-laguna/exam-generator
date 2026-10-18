import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { QuestionCard } from "../components/QuestionCard";
import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function QuestionsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [documentId, setDocumentId] = useState<number | "">("");
  const [type, setType] = useState<"" | "mcq" | "true_false">("");
  const [selected, setSelected] = useState<number[]>([]);
  const [title, setTitle] = useState("");

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: async () => unwrap(await api.GET("/api/v1/documents")),
  });

  const questions = useQuery({
    queryKey: ["questions", documentId, type],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/questions", {
          params: { query: { ...(documentId !== "" ? { document_id: documentId } : {}), ...(type ? { type } : {}) } },
        }),
      ),
  });

  const remove = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.DELETE("/api/v1/questions/{question_id}", {
        params: { path: { question_id: id } },
      });
      if (error !== undefined) unwrap({ error, response });
      return id;
    },
    onSuccess: (id) => {
      setSelected((current) => current.filter((x) => x !== id));
      return queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
  });

  const save = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/question-sets", { body: { title: title.trim(), question_ids: selected } })),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["sets"] });
      navigate(`/sets/${created.id}`);
    },
  });

  const toggle = (id: number) =>
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <>
      <h1>Questions</h1>
      <div className="row filters">
        <label>
          Document
          <select value={documentId} onChange={(e) => setDocumentId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">All</option>
            {documents.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        </label>
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option value="">All</option>
            <option value="mcq">Multiple choice</option>
            <option value="true_false">True / false</option>
          </select>
        </label>
      </div>
      <ErrorText error={questions.error ?? remove.error} />

      {selected.length > 0 ? (
        <form onSubmit={submit} className="card row sticky">
          <strong>{selected.length} selected</strong>
          <input
            aria-label="Set title"
            placeholder="Set title, e.g. Unit 1 quiz"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button type="submit" disabled={!title.trim() || save.isPending}>
            Save as set
          </button>
          <button type="button" className="link" onClick={() => setSelected([])}>
            Clear
          </button>
          <ErrorText error={save.error} />
        </form>
      ) : null}

      {questions.data?.length === 0 ? (
        <p>
          No questions yet. <Link to="/generate">Generate some</Link>.
        </p>
      ) : null}
      {questions.data?.map((q) => (
        <QuestionCard
          key={q.id}
          question={q}
          actions={
            <>
              <label className="check">
                <input type="checkbox" checked={selected.includes(q.id)} onChange={() => toggle(q.id)} />
                Select
              </label>
              <button
                type="button"
                className="danger"
                onClick={() => window.confirm("Delete this question?") && remove.mutate(q.id)}
              >
                Delete
              </button>
            </>
          }
        />
      ))}
    </>
  );
}
