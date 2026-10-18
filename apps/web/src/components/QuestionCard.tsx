import type { ReactNode } from "react";

import type { Schema } from "@learn-assistant/api-client";

export type Question = Schema["BankQuestionOut"];
export type Citation = Schema["CitationOut"];

export function formatCitation(c: Citation): string {
  const lines = c.line_start === c.line_end ? `line ${c.line_start}` : `lines ${c.line_start}–${c.line_end}`;
  return `${c.document}, page ${c.page}, ${lines}`;
}

interface Props {
  question: Question;
  number?: number;
  /** Controls such as a selection checkbox or a delete button. */
  actions?: ReactNode;
}

/** A question as the teacher sees it: correct option marked, explanation and sources shown. */
export function QuestionCard({ question, number, actions }: Props) {
  const options =
    question.type === "true_false"
      ? ([
          ["A", "True"],
          ["B", "False"],
        ] as const)
      : Object.entries(question.options);

  return (
    <article className="card question">
      <header className="question-head">
        <span className="badge">{question.type === "mcq" ? "Multiple choice" : "True / false"}</span>
        {actions ? <div className="actions">{actions}</div> : null}
      </header>
      <h3>
        {number !== undefined ? `${number}. ` : ""}
        {question.stem}
      </h3>
      <ul className="options">
        {options.map(([letter, text]) => (
          <li key={letter} className={letter === question.correct_option ? "correct" : undefined}>
            <strong>{letter}.</strong> {text}
            {letter === question.correct_option ? <span className="sr-only"> (correct answer)</span> : null}
          </li>
        ))}
      </ul>
      <p className="explanation">{question.explanation}</p>
      <ul className="citations">
        {question.citations.map((c, i) => (
          <li key={i}>
            <span className="source">{formatCitation(c)}</span>
            <q>{c.quote}</q>
          </li>
        ))}
      </ul>
    </article>
  );
}
