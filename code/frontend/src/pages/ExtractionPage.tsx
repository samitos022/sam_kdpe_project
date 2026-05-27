import { Card } from "../components/ui/Card";
import { MetricsBar } from "../components/extraction/MetricsBar";
import { ExtractionPanel } from "../components/extraction/ExtractionPanel";
import type { Schema } from "../types";


// ─── ExtractionPage ───────────────────────────────────────────────────────────

interface ExtractionPageProps {
  schema: Schema | null;
  extractionStatus: import("../types").ExtractionStatus;
  extractionError: string | null;
  nValidationDocs: number;
  onStartExtraction: (maxDocs?: number) => void;
}

export function ExtractionPage({
  schema,
  extractionStatus,
  extractionError,
  nValidationDocs,
  onStartExtraction,
}: ExtractionPageProps) {
  return (
    <div className="flex flex-col gap-4 overflow-y-auto p-6">
      <h1 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
        Batch extraction
      </h1>

      {schema && (
        <div className="flex gap-2 flex-wrap">
          <span className="rounded-full bg-violet-100 px-3 py-1 text-xs text-violet-700">
            v{schema.version} · {schema.entity_classes.length} classes
          </span>
          <span className="rounded-full bg-teal-100 px-3 py-1 text-xs text-teal-700">
            {schema.relation_types.length} relation types
          </span>
          {schema.frozen && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">
              frozen ✓
            </span>
          )}
        </div>
      )}

      <ExtractionPanel
        status={extractionStatus}
        error={extractionError}
        nValidationDocs={nValidationDocs}
        onStart={onStartExtraction}
      />

      {(extractionStatus.status === "running" || extractionStatus.status === "done") && (
        <MetricsBar status={extractionStatus} />
      )}

      <Card className="text-xs text-zinc-500 space-y-1">
        <p className="font-medium text-zinc-600 dark:text-zinc-300">What happens during extraction</p>
        <p>Each document is processed with the GIV self-repair loop.</p>
        <p>Entities and relations are written to Neo4j tagged with this session.</p>
        <p>UIR and SDR are computed in real time as documents are processed.</p>
      </Card>
    </div>
  );
}