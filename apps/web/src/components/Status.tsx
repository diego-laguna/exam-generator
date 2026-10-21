/** Maps raw API status strings to a friendly label. */
const STATUS_LABELS: Record<string, string> = {
  pending:     "Pending",
  queued:      "Queued",
  processing:  "Processing",
  running:     "Running",
  ingesting:   "Ingesting",
  generating:  "Generating",
  ready:       "Ready",
  done:        "Done",
  finished:    "Finished",
  failed:      "Failed",
  in_progress: "In progress",
  submitted:   "Submitted",
  open:        "Open",
  ended:       "Ended",
};

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <p role="alert" className="alert-error">
      <span aria-hidden="true">⚠️</span> {message}
    </p>
  );
}

/** `label` overrides the default text, e.g. "Ended early" with the `ended` colours. */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`badge status-${status}`}>{label ?? STATUS_LABELS[status] ?? status}</span>;
}
