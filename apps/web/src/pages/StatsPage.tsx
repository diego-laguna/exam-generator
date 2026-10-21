import { useQuery } from "@tanstack/react-query";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

const pct = (accuracy: number | null) =>
  accuracy === null ? "–" : `${Math.round(accuracy * 100)}%`;

function accuracyClass(accuracy: number | null): string {
  if (accuracy === null) return "";
  if (accuracy >= 0.75) return "";      // ok (green default)
  if (accuracy >= 0.5) return "mid";    // warn
  return "low";                         // danger
}

export function StatsPage() {
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/stats")),
  });
  const attempted = stats.data?.domains.reduce((sum, d) => sum + d.attempted, 0) ?? 0;

  return (
    <>
      <h1>📊 My Stats</h1>
      <p className="hint">
        Accuracy per exam domain and task statement. Practice answers and finished exams count.
      </p>
      <ErrorText error={stats.error} />

      {stats.data && attempted === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">📈</span>
          <strong>No data yet</strong>
          <p>Complete a practice session to see your accuracy here.</p>
        </div>
      ) : null}

      {stats.data?.domains.map((d) => {
        const cls = accuracyClass(d.accuracy);
        return (
          <section key={d.domain_id} className="card">
            <div className="row" style={{ marginBottom: "0.75rem" }}>
              <h2 className="grow" style={{ margin: 0 }}>
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
              <strong style={{ minWidth: "3rem", textAlign: "right" }}>{pct(d.accuracy)}</strong>
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
                      <span className={accuracyClass(t.accuracy) === "low" ? "error" : accuracyClass(t.accuracy) === "mid" ? "" : "ok-text"}>
                        {pct(t.accuracy)}
                      </span>
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
