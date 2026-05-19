import { Card } from "../ui/Card";
import { ProgressBar } from "../ui/ProgressBar";
import { Button } from "../ui/Button";
import type { ExtractionStatus } from "../../types";

// ─── ExtractionPanel ─────────────────────────────────────────────────────────

interface ExtractionPanelProps {
  status: ExtractionStatus;
  error: string | null;
  onStart: () => void;
}

export function ExtractionPanel({ status, error, onStart }: ExtractionPanelProps) {
  const isRunning = status.status === "running";
  const isDone = status.status === "done";
  const notStarted = status.status === "not_started";

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
            Batch extraction
          </h2>
          <p className="text-xs text-zinc-400">
            {isDone
              ? `Completed — ${status.processed} documents processed`
              : isRunning
              ? `Processing ${status.processed} / ${status.total} documents…`
              : "Extract entities and relations from the validation corpus"}
          </p>
        </div>
        {!isDone && (
          <Button onClick={onStart} loading={isRunning} disabled={isRunning}>
            {notStarted ? "Start extraction" : "Running…"}
          </Button>
        )}
        {isDone && (
          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700">
            Done ✓
          </span>
        )}
      </div>

      {(isRunning || isDone) && (
        <ProgressBar value={status.progress_pct} label="Progress" />
      )}

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </p>
      )}

      {status.errors.length > 0 && (
        <details className="text-xs text-zinc-400">
          <summary className="cursor-pointer">
            {status.errors.length} document(s) failed after all repair attempts
          </summary>
          <ul className="mt-1 space-y-0.5 pl-3">
            {status.errors.slice(0, 10).map((e) => (
              <li key={e.doc_id}>
                <span className="font-mono">{e.doc_id}</span>: {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

