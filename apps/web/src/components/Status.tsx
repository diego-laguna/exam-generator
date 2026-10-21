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

export function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  return <span className={`badge status-${status}`}>{label}</span>;
}
