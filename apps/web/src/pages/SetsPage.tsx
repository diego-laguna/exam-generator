import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { EmptyState, PageHeader } from "../components/Page";
import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

export function SetsPage() {
  const sets = useQuery({
    queryKey: ["sets"],
    queryFn: async () => unwrap(await api.GET("/api/v1/question-sets")),
  });

  return (
    <>
      <PageHeader title="Question sets" subtitle="Saved selections of questions, ready to print for students or as an answer key." />
      <ErrorText error={sets.error} />
      {sets.data?.length === 0 ? (
        <EmptyState icon="📦" title="No sets yet">
          Select questions on the <Link to="/questions">Questions</Link> page and save them as a set.
        </EmptyState>
      ) : null}
      <ul className="list tile-grid">
        {sets.data?.map((s) => (
          <li key={s.id}>
            <Link to={`/sets/${s.id}`} className="card tile">
              <strong className="tile-title">{s.title}</strong>
              <span className="hint">
                {s.question_count} question{s.question_count === 1 ? "" : "s"} &middot; updated{" "}
                {new Date(s.updated_at).toLocaleDateString()}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
