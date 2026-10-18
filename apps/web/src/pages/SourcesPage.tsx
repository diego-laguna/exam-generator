import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../auth";
import { ErrorText, StatusBadge } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function SourcesPage() {
  const { state } = useAuth();
  const isAdmin = state.status === "authenticated" && state.role === "admin";
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");

  const sources = useQuery({
    queryKey: ["sources"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sources")),
    refetchInterval: (query) =>
      query.state.data?.some((s) => s.status === "pending" || s.status === "ingesting") ? 2000 : false,
  });

  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/sources", { body: { url: url.trim() } })),
    onSuccess: () => {
      setUrl("");
      return queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  const remove = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.DELETE("/api/v1/sources/{source_id}", {
        params: { path: { source_id: id } },
      });
      if (error !== undefined) unwrap({ error, response });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <>
      <h1>Documentation sources</h1>
      <p className="hint">
        AWS documentation pages used by the student exam module. Only HTML pages on the allowed AWS hosts are accepted;
        for PDFs, teachers use Documents.
      </p>
      {isAdmin ? (
        <form onSubmit={submit} className="card row">
          <label className="grow">
            Page URL
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html"
              required
            />
          </label>
          <button type="submit" disabled={add.isPending}>
            Add source
          </button>
        </form>
      ) : null}
      <ErrorText error={add.error ?? remove.error ?? sources.error} />

      {sources.data?.length === 0 ? <p>No sources yet.</p> : null}
      <ul className="list">
        {sources.data?.map((s) => (
          <li key={s.id} className="card row">
            <div className="grow">
              <strong>{s.title ?? s.url}</strong>
              <div className="hint">
                {s.title ? `${s.url} · ` : ""}
                {s.chunk_count} chunks
              </div>
              {s.error ? <p className="error">{s.error}</p> : null}
            </div>
            <StatusBadge status={s.status} />
            {isAdmin ? (
              <button
                type="button"
                className="danger"
                onClick={() => window.confirm("Delete this source and its chunks?") && remove.mutate(s.id)}
              >
                Delete
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}
