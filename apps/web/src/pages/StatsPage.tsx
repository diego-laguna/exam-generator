import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "../components/Page";
import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

const pct = (accuracy: number | null) =>
  accuracy === null ? "–" : `${Math.round(accuracy * 100)}%`;

/** "" (good, green), "mid" (warn) or "low" (danger); no answers counts as good so nothing is flagged. */
function accuracyClass(accuracy: number | null): string {
  if (accuracy === null || accuracy >= 0.75) return "";
  return accuracy >= 0.5 ? "mid" : "low";
}

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
        Accuracy per exam domain and task statement. Practice answers and finished exams count.
      </p>
      <ErrorText error={stats.error} />

      {stats.data && attempted === 0 ? (
        <EmptyState icon="📈" title="No data yet">
          Complete a practice session to see your accuracy here.
        </EmptyState>
      ) : null}

      {stats.data?.domains.map((d) => {
        const cls = accuracyClass(d.accuracy);
        return (
          <section key={d.domain_id} className="card">
            <div className="row domain-head">
              <h2 className="grow">
                {d.domain_id}. {d.name}
              </h2>
              <div className="progress-wrap">
                <div className="progress-track">
                  <div
                    className={`progress-fill ${cls}`}
                    style={{ width: `${Math.round((d.accuracy ?? 0) * 100)}%` }}
                  />
                </div>
              </div>
              <strong className="domain-pct">{pct(d.accuracy)}</strong>
              <span className="hint">{d.correct} / {d.attempted}</span>
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
                      <strong>{t.code}</strong>{" "}
                      <span className="hint">{t.description}</span>
                    </td>
                    <td>{t.correct}</td>
                    <td>{t.attempted}</td>
                    <td>
                      <span className={`pct ${accuracyClass(t.accuracy)}`}>{pct(t.accuracy)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </>
  );
}
