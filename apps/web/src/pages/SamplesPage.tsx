import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import type { Schema } from "@exam-generator/api-client";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

type Sample = Schema["SampleIn"];
type Letter = "A" | "B" | "C" | "D";
const LETTERS: Letter[] = ["A", "B", "C", "D"];

const EXAMPLE = JSON.stringify(
  [
    {
      task_statement: "1.1",
      stem: "A company needs to give an application temporary access to an S3 bucket. What should it use?",
      options: { A: "An IAM role", B: "A root access key", C: "A public bucket", D: "A shared password" },
      correct_option: "A",
    },
  ],
  null,
  2,
);

export function SamplesPage() {
  const [target, setTarget] = useState("");
  const [stem, setStem] = useState("");
  const [options, setOptions] = useState<Record<Letter, string>>({ A: "", B: "", C: "", D: "" });
  const [correct, setCorrect] = useState<Letter>("A");
  const [bulk, setBulk] = useState("");
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // The stats endpoint doubles as the list of domains and task statements.
  const taxonomy = useQuery({
    queryKey: ["stats"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/stats")),
  });

  const create = useMutation({
    mutationFn: async (samples: Sample[]) => unwrap(await api.POST("/api/v1/samples", { body: { samples } })),
    onSuccess: (result) => setDone(`Added ${result.created} sample${result.created === 1 ? "" : "s"}.`),
  });

  function submitOne(event: FormEvent) {
    event.preventDefault();
    setDone(null);
    const [kind, value] = target.split(":");
    const sample: Sample = {
      stem: stem.trim(),
      options,
      correct_option: correct,
      ...(kind === "t" ? { task_statement: value } : { domain_id: Number(value) }),
    };
    create.mutate([sample], {
      onSuccess: () => {
        setStem("");
        setOptions({ A: "", B: "", C: "", D: "" });
      },
    });
  }

  function submitBulk(event: FormEvent) {
    event.preventDefault();
    setDone(null);
    setBulkError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(bulk);
    } catch {
      setBulkError("That is not valid JSON.");
      return;
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      setBulkError("Provide a non-empty JSON array of samples.");
      return;
    }
    create.mutate(parsed as Sample[], { onSuccess: () => setBulk("") });
  }

  return (
    <>
      <h1>Sample questions</h1>
      <p className="hint">
        Style examples for the student module. Add them one at a time, or paste several as JSON. Either the whole batch is
        saved or nothing is.
      </p>
      {done ? (
        <p role="status" className="ok-text">
          {done}
        </p>
      ) : null}
      <ErrorText error={create.error ?? taxonomy.error} />

      <form onSubmit={submitOne} className="card stack">
        <h2>One sample</h2>
        <label>
          Topic
          <select value={target} onChange={(e) => setTarget(e.target.value)} required>
            <option value="">Choose a domain or task statement</option>
            {taxonomy.data?.domains.map((d) => (
              <optgroup key={d.domain_id} label={`${d.domain_id}. ${d.name}`}>
                <option value={`d:${d.domain_id}`}>Whole domain {d.domain_id}</option>
                {d.task_statements.map((t) => (
                  <option key={t.code} value={`t:${t.code}`}>
                    {t.code} {t.description}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label>
          Question (at least 20 characters)
          <textarea value={stem} onChange={(e) => setStem(e.target.value)} minLength={20} rows={3} required />
        </label>
        {LETTERS.map((letter) => (
          <label key={letter}>
            Option {letter}
            <input
              value={options[letter]}
              onChange={(e) => setOptions((current) => ({ ...current, [letter]: e.target.value }))}
              required
            />
          </label>
        ))}
        <label>
          Correct option
          <select value={correct} onChange={(e) => setCorrect(e.target.value as Letter)}>
            {LETTERS.map((letter) => (
              <option key={letter}>{letter}</option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={create.isPending}>
          Add sample
        </button>
      </form>

      <form onSubmit={submitBulk} className="card stack">
        <h2>Several samples (JSON)</h2>
        <label>
          JSON array
          <textarea
            value={bulk}
            onChange={(e) => setBulk(e.target.value)}
            rows={8}
            placeholder={EXAMPLE}
            spellCheck={false}
          />
        </label>
        {bulkError ? (
          <p role="alert" className="alert-error">
            {bulkError}
          </p>
        ) : null}
        <button type="submit" disabled={create.isPending || !bulk.trim()}>
          Add samples
        </button>
      </form>
    </>
  );
}
