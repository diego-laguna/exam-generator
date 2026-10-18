import { useQuery } from "@tanstack/react-query";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

const percent = (accuracy: number | null) => (accuracy === null ? "–" : `${Math.round(accuracy * 100)}%`);

export function StatsPage() {
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/stats")),
  });
  const attempted = stats.data?.domains.reduce((sum, d) => sum + d.attempted, 0) ?? 0;

  return (
    <>
      <h1>My stats</h1>
      <p className="hint">
        Accuracy per exam domain and task statement. Practice answers and finished exams count; answers in an exam that is
        still running do not.
      </p>
      <ErrorText error={stats.error} />
      {stats.data && attempted === 0 ? <p>No answers counted yet. Take a practice session to see your accuracy here.</p> : null}
      {stats.data?.domains.map((d) => (
        <section key={d.domain_id} className="card">
          <div className="row">
            <h2 className="grow">
              {d.domain_id}. {d.name}
            </h2>
            <strong>{percent(d.accuracy)}</strong>
            <span className="hint">
              {d.correct} / {d.attempted} correct
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th scope="col">Task statement</th>
                <th scope="col">Correct</th>
                <th scope="col">Attempted</th>
                <th scope="col">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {d.task_statements.map((t) => (
                <tr key={t.code}>
                  <td>
                    {t.code} {t.description}
                  </td>
                  <td>{t.correct}</td>
                  <td>{t.attempted}</td>
                  <td>{percent(t.accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}
