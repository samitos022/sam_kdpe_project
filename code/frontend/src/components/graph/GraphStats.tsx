import { classHex, formatPct } from "../../lib/utils";
import { Card } from "../ui/Card";
import { Badge} from "../ui/Badge";

import type { SchemaUtilization } from "../../types";


// ─── GraphStats ──────────────────────────────────────────────────────────────

interface GraphStatsProps {
  utilization: SchemaUtilization;
}

export function GraphStats({ utilization: u }: GraphStatsProps) {
  const metrics = [
    { label: "SUR", value: formatPct(u.sur), help: "Schema Utilization Rate — classes populated" },
    { label: "Relation SUR", value: formatPct(u.relation_sur), help: "Relations populated" },
    { label: "RTE", value: u.relation_entropy.toFixed(3), help: "Relation Type Entropy (bits)" },
    { label: "ONR", value: formatPct(u.orphan_rate), help: "Orphan Node Rate — nodes with no edges" },
    { label: "Nodes", value: u.total_nodes.toLocaleString() },
    { label: "Edges", value: u.total_edges.toLocaleString() },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {metrics.map((m) => (
          <Card key={m.label} className="p-3 text-center">
            <p className="text-lg font-semibold text-zinc-800 dark:text-zinc-100">{m.value}</p>
            <p className="text-[10px] text-zinc-400" title={m.help}>{m.label}</p>
          </Card>
        ))}
      </div>

      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-400">
          Class population
        </p>
        <div className="space-y-1.5">
          {Object.entries(u.populated_classes).map(([cls, count]) => (
            <div key={cls} className="flex items-center gap-2 text-white">
              <Badge className={`w-28 justify-center ${classHex(cls)}`}>{cls}</Badge>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                <div
                  className="h-full rounded-full bg-violet-400"
                  style={{ width: `${Math.min(100, (count / u.total_nodes) * 100 * 5)}%` }}
                />
              </div>
              <span className="w-10 text-right text-xs text-zinc-400">{count}</span>
            </div>
          ))}
          {u.unpopulated_classes.map((cls) => (
            <div key={cls} className="flex items-center gap-2 opacity-40">
              <Badge className="w-28 justify-center">{cls}</Badge>
              <div className="h-2 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800" />
              <span className="w-10 text-right text-xs text-zinc-400">0</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}