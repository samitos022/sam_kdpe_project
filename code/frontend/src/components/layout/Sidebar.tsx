import type { AppView, Schema } from "../../types";
import { NavLink } from "./NavLink";

// ─── Sidebar ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  sessionId: string | null;
  currentView: AppView;
  onNavigate: (view: AppView) => void;
  frozen: boolean;
  extractionDone: boolean;
  schema?: Schema | null;
}

export function Sidebar({
  sessionId,
  currentView,
  onNavigate,
  frozen,
  extractionDone,
  schema,
}: SidebarProps) {
  const hasSession = !!sessionId;

  return (
    <div className="flex flex-col gap-1 p-3 h-full overflow-y-auto">
      <div className="mb-4 px-2 pt-2">
        <p className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          Graph Extraction
        </p>
      </div>

      <NavLink
        label="New session"
        icon="⊕"
        active={currentView === "home"}
        onClick={() => onNavigate("home")}
      />

      <NavLink
        label="Schema chat"
        icon="💬"
        active={currentView === "chat"}
        disabled={!hasSession}
        onClick={() => onNavigate("chat")}
      />

      <NavLink
        label="Batch extraction"
        icon="⚙"
        active={currentView === "extraction"}
        disabled={!frozen}
        onClick={() => onNavigate("extraction")}
        badge={frozen ? undefined : "freeze first"}
      />

      <NavLink
        label="Graph & metrics"
        icon="◈"
        active={currentView === "graph"}
        disabled={!extractionDone}
        onClick={() => onNavigate("graph")}
        badge={extractionDone ? undefined : "extract first"}
      />

      {/* Schema info summary */}
      {schema && (
        <div className="mt-auto px-2 pb-2 pt-4 border-t border-zinc-200 dark:border-zinc-700">
          <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-2">
            Schema v{schema.version}
          </p>
          <div className="space-y-1 text-[11px] text-zinc-600 dark:text-zinc-400">
            <div className="flex justify-between">
              <span>Classes:</span>
              <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-200">
                {schema.entity_classes.length}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Relations:</span>
              <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-200">
                {schema.relation_types.length}
              </span>
            </div>
            {schema.frozen && (
              <div className="mt-2 inline-block rounded bg-amber-50 dark:bg-amber-950 px-2 py-1 text-amber-700 dark:text-amber-300">
                🔒 Frozen
              </div>
            )}
          </div>
        </div>
      )}

      {sessionId && !schema && (
        <div className="mt-auto px-2 pb-2 pt-4">
          <p className="text-[10px] text-zinc-400 truncate">
            Session: <span className="font-mono">{sessionId}</span>
          </p>
        </div>
      )}
    </div>
  );
}

