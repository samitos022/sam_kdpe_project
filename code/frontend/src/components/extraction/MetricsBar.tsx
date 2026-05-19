import { Card } from "../ui/Card";
import { formatPct } from "../../lib/utils";
import type { ExtractionStatus } from "../../types";

// ─── MetricsBar ──────────────────────────────────────────────────────────────

interface MetricsBarProps {
  status: ExtractionStatus;
}

export function MetricsBar({ status }: MetricsBarProps) {
  const m = status.metrics;
  const tiles = [
    { label: "Entities extracted", value: m.total_entities.toLocaleString() },
    { label: "Relations extracted", value: m.total_relations.toLocaleString() },
    { label: "UIR", value: formatPct(status.uir), help: "Unmapped Instance Rate" },
    { label: "SDR", value: formatPct(status.sdr), help: "Schema Drift Rate" },
    { label: "Repair iterations", value: m.total_repairs.toLocaleString() },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {tiles.map((t) => (
        <Card key={t.label} className="text-center p-3">
          <p className="text-lg font-semibold text-zinc-800 dark:text-zinc-100">{t.value}</p>
          <p className="text-[10px] text-zinc-400" title={t.help}>
            {t.label}
          </p>
        </Card>
      ))}
    </div>
  );
}