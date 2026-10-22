import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState, PageHeader } from "../components/Page";
import { ErrorText, StatusBadge } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: async () => unwrap(await api.GET("/api/v1/documents")),
    // Keep polling while the server is still reading a PDF.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false,
  });

  const upload = useMutation({
    mutationFn: async (pdf: File) => {
      const form = new FormData();
      form.append("file", pdf);
      return unwrap(await api.POST("/api/v1/documents", { body: { file: "" }, bodySerializer: () => form }));
    },
    onSuccess: () => {
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      return queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const remove = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.DELETE("/api/v1/documents/{document_id}", {
        params: { path: { document_id: id } },
      });
      if (error !== undefined) unwrap({ error, response });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (file) upload.mutate(file);
  }

  return (
    <>
      <PageHeader
        title="Documents"
        subtitle="Upload the PDFs your questions should come from. Each question cites the page and lines it is based on."
      />
      <form onSubmit={submit} className="card upload-card">
        <label className="grow">
          PDF file
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={!file || upload.isPending}>
          {upload.isPending ? "Uploading…" : "Upload"}
        </button>
        <p className="hint upload-hint">PDFs need a text layer; scanned documents are rejected. Maximum 25 MB.</p>
      </form>
      <ErrorText error={upload.error ?? remove.error ?? documents.error} />

      {documents.data?.length === 0 ? (
        <EmptyState icon="📄" title="No documents yet">
          Upload a PDF above to start generating questions.
        </EmptyState>
      ) : null}
      <ul className="list">
        {documents.data?.map((d) => (
          <li key={d.id} className="card item">
            <span className="item-icon" aria-hidden="true">
              📄
            </span>
            <div className="grow">
              <strong className="item-title">{d.filename}</strong>
              <div className="hint">
                {d.page_count ? `${d.page_count} pages · ` : ""}
                {d.chunk_count} chunks
              </div>
              {d.error ? <p className="item-error">{d.error}</p> : null}
            </div>
            <StatusBadge status={d.status} />
            <button
              type="button"
              className="danger"
              onClick={() => window.confirm(`Delete ${d.filename}? Its questions are kept.`) && remove.mutate(d.id)}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
