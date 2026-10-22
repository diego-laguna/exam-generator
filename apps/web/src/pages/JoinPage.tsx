import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { EmptyState, Stat } from "../components/Page";
import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { formatClock, useCountdown } from "../format";
import { loadParticipantToken, publicApi, saveParticipantToken } from "../publicApi";

/** The page a student opens from the teacher's link. No account: a name is enough. */
export function JoinPage() {
  const token = useParams().token ?? "";
  const [secret, setSecret] = useState(() => loadParticipantToken(token));

  const info = useQuery({
    queryKey: ["join", token],
    queryFn: async () => unwrap(await publicApi.GET("/api/v1/join/{token}", { params: { path: { token } } })),
    retry: false,
  });

  return (
    <main className="join">
      <p className="join-brand">
        <span aria-hidden="true">🎓</span> ExamGen
      </p>
      <h1>{info.data?.exam_title ?? "Exam"}</h1>
      {info.isPending ? <p>Loading&hellip;</p> : null}
      {info.error ? <p role="alert" className="alert-error">This exam link is not valid.</p> : null}
      {info.data && secret === null ? (
        <NameForm
          token={token}
          info={info.data}
          onJoined={(value) => {
            saveParticipantToken(token, value);
            setSecret(value);
          }}
        />
      ) : null}
      {info.data && secret !== null ? <TakeExam token={token} secret={secret} /> : null}
    </main>
  );
}

function NameForm({
  token,
  info,
  onJoined,
}: {
  token: string;
  info: { question_count: number; duration_minutes: number; status: "open" | "ended" };
  onJoined: (secret: string) => void;
}) {
  const [name, setName] = useState("");
  const join = useMutation({
    mutationFn: async () =>
      unwrap(await publicApi.POST("/api/v1/join/{token}/participants", { params: { path: { token } }, body: { name } })),
    onSuccess: (joined) => onJoined(joined.participant_token),
  });

  if (info.status === "ended") {
    return (
      <EmptyState icon="⏹️" title="Closed">
        This exam session has ended.
      </EmptyState>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) join.mutate();
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <div className="stat-grid">
        <Stat label="Questions" value={info.question_count} />
        <Stat label="Minutes" value={info.duration_minutes} />
      </div>
      <p className="hint">
        The time limit counts from when your teacher started the session, not from when you join. Your answers are
        saved as you go.
      </p>
      <label>
        Your name
        <input value={name} maxLength={100} autoComplete="name" onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="submit" disabled={!name.trim() || join.isPending}>
        Start exam
      </button>
      <ErrorText error={join.error} />
    </form>
  );
}

function TakeExam({ token, secret }: { token: string; secret: string }) {
  const queryClient = useQueryClient();
  const header = { "X-Participant-Token": secret };

  const state = useQuery({
    queryKey: ["join", token, "me"],
    queryFn: async () =>
      unwrap(await publicApi.GET("/api/v1/join/{token}/me", { params: { path: { token }, header } })),
    retry: false,
  });

  const save = useMutation({
    mutationFn: async ({ key, option }: { key: string; option: string }) => {
      const { error, response } = await publicApi.PUT("/api/v1/join/{token}/answers/{question_key}", {
        params: { path: { token, question_key: key }, header },
        body: { selected_option: option },
      });
      if (error !== undefined) unwrap({ error, response });
    },
    onSuccess: (_data, { key, option }) =>
      queryClient.setQueryData(["join", token, "me"], (old: typeof state.data) =>
        old ? { ...old, answers: { ...old.answers, [key]: option } } : old,
      ),
    // Time ran out or the teacher ended the session: reload to show the result.
    onError: () => void queryClient.invalidateQueries({ queryKey: ["join", token, "me"] }),
  });

  const submit = useMutation({
    mutationFn: async () =>
      unwrap(await publicApi.POST("/api/v1/join/{token}/submit", { params: { path: { token }, header } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["join", token, "me"] }),
  });

  const active = state.data?.status === "in_progress";
  const secondsLeft = useCountdown(active ? state.data?.ends_at : null);

  if (state.isPending) return <p>Loading&hellip;</p>;
  if (state.error) return <ErrorText error={state.error} />;
  const me = state.data;

  if (me.result) {
    return (
      <>
        <section className="card score-hero" role="status">
          <span className="score-sub">{me.name}, you scored</span>
          <strong className="score-number">
            {me.result.score} / {me.result.total}
          </strong>
          <span className="score-sub">Review your answers below.</span>
        </section>
        <ol className="list">
          {me.result.review.map((r, index) => (
            <li key={r.key} className="card question-take">
              <h3>
                {index + 1}. {r.stem}
              </h3>
              <ul className="options">
                {Object.entries(r.options).map(([letter, text]) => (
                  <li
                    key={letter}
                    className={letter === r.correct_option ? "correct" : letter === r.selected_option ? "wrong-pick" : ""}
                  >
                    <strong>{letter}.</strong> {text}
                    {letter === r.correct_option ? <span className="tag correct">correct answer</span> : null}
                    {letter === r.selected_option && letter !== r.correct_option ? (
                      <span className="tag yours">your answer</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {r.selected_option === null ? <p className="hint">Not answered.</p> : null}
              <p className="explanation">{r.explanation}</p>
            </li>
          ))}
        </ol>
      </>
    );
  }

  const answered = Object.keys(me.answers).length;
  return (
    <>
      <div className="card sticky row" role="timer">
        <span className={secondsLeft !== null && secondsLeft <= 60 ? "timer warn" : "timer"}>
          Time left: <strong>{secondsLeft === null ? "–" : formatClock(secondsLeft)}</strong>
        </span>
        <span className="hint grow">
          {answered} of {me.questions.length} answered
        </span>
        <span className="progress-track answered-bar" aria-hidden="true">
          <span className="progress-fill" style={{ width: `${Math.round((100 * answered) / me.questions.length)}%` }} />
        </span>
        <button
          type="button"
          disabled={submit.isPending}
          onClick={() =>
            (answered === me.questions.length ||
              window.confirm(`You answered ${answered} of ${me.questions.length}. Submit anyway?`)) &&
            submit.mutate()
          }
        >
          Submit exam
        </button>
      </div>
      <ErrorText error={save.error ?? submit.error} />
      {secondsLeft === 0 ? (
        <p role="alert" className="alert-error">
          Time is up.{" "}
          <button type="button" className="link" onClick={() => void queryClient.invalidateQueries({ queryKey: ["join", token, "me"] })}>
            Show my result
          </button>
        </p>
      ) : null}
      {me.questions.map((q, index) => (
        <fieldset key={q.key} className="card question-take">
          <legend>
            {index + 1}. {q.stem}
          </legend>
          {Object.entries(q.options).map(([letter, text]) => (
            <label key={letter} className="check option">
              <input
                type="radio"
                name={q.key}
                value={letter}
                checked={me.answers[q.key] === letter}
                onChange={() => save.mutate({ key: q.key, option: letter })}
              />
              {letter}. {text}
            </label>
          ))}
        </fieldset>
      ))}
    </>
  );
}
