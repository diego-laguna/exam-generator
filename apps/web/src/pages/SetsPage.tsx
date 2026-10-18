import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

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
      <h1>Question sets</h1>
      <ErrorText error={sets.error} />
      {sets.data?.length === 0 ? (
        <p>
          No sets yet. Select questions on the <Link to="/questions">Questions</Link> page and save them as a set.
        </p>
      ) : null}
      <ul className="list">
        {sets.data?.map((s) => (
          <li key={s.id} className="card row">
            <Link to={`/sets/${s.id}`} className="grow">
              <strong>{s.title}</strong>
            </Link>
            <span className="hint">
              {s.question_count} question{s.question_count === 1 ? "" : "s"} &middot; updated{" "}
              {new Date(s.updated_at).toLocaleDateString()}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
