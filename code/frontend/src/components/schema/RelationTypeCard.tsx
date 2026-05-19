import { classColor } from "../../lib/utils";
import { Badge } from "../ui/Badge";
import type { RelationType } from "../../types";

// ─── RelationTypeCard ────────────────────────────────────────────────────────

export function RelationTypeCard({ rel }: { rel: RelationType }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-zinc-100 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-800/40">
      <Badge className={classColor(rel.domain)}>{rel.domain}</Badge>
      <span className="text-xs font-mono text-zinc-500">—{rel.name}→</span>
      <Badge className={classColor(rel.range)}>{rel.range}</Badge>
      <p className="ml-auto max-w-[140px] truncate text-[10px] text-zinc-400">
        {rel.description}
      </p>
    </div>
  );
}