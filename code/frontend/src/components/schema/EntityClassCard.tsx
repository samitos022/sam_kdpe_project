import { classColor } from "../../lib/utils";
import { Badge } from "../ui/Badge";
import type { EntityClass } from "../../types";


// ─── EntityClassCard ─────────────────────────────────────────────────────────

export function EntityClassCard({ cls }: { cls: EntityClass }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-zinc-100 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-800/40">
      <Badge className={classColor(cls.name)}>{cls.name}</Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-zinc-600 dark:text-zinc-400">{cls.description}</p>
        {cls.examples.length > 0 && (
          <p className="mt-0.5 truncate text-[10px] text-zinc-400">
            e.g. {cls.examples.slice(0, 3).join(", ")}
          </p>
        )}
      </div>
    </div>
  );
}