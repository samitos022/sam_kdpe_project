import { Button } from "../components/ui/Button";
import { GraphStats } from "../components/graph/GraphStats";
import { GraphCanvas } from "../components/graph/GraphCanvas";


// ─── GraphPage ────────────────────────────────────────────────────────────────

interface GraphPageProps {
  nodes: import("../types").GraphNode[];
  edges: import("../types").GraphEdge[];
  utilization: import("../types").SchemaUtilization | null;
  loading: boolean;
  onLoad: () => void;
  onLoadUtilization: () => void;
}

export function GraphPage({
  nodes,
  edges,
  utilization,
  loading,
  onLoad,
  onLoadUtilization,
}: GraphPageProps) {
  return (
    <div className="flex h-full">
      {/* Graph canvas */}
      <div className="relative flex-1 border-r border-zinc-200 dark:border-zinc-800">
        <div className="absolute left-3 top-3 z-10 flex gap-2">
          <Button size="sm" variant="secondary" onClick={onLoad} loading={loading}>
            Load graph
          </Button>
        </div>
        <GraphCanvas nodes={nodes} edges={edges} />
      </div>

      {/* Right panel: metrics */}
      <div className="w-72 flex-shrink-0 overflow-y-auto p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Evaluation metrics
          </h2>
          <Button size="sm" variant="ghost" onClick={onLoadUtilization}>
            Refresh
          </Button>
        </div>

        {utilization ? (
          <GraphStats utilization={utilization} />
        ) : (
          <div className="flex justify-center py-8">
            <Button size="sm" variant="secondary" onClick={onLoadUtilization}>
              Compute metrics
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}