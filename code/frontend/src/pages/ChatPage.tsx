import { useRef, useState, useEffect } from "react";
import { Spinner } from "../components/ui/Spinner";
import { SchemaPanel } from "../components/schema/SchemaPanel";
import { ConvergenceChart } from "../components/schema/ConvergenceChart";
import { ChatPanel } from "../components/chat/ChatPanel";
import type { Schema } from "../types";


// ─── ChatPage ────────────────────────────────────────────────────────────────

interface ChatPageProps {
  sessionId: string;
  schema: Schema | null;
  turns: Array<{ role: "user" | "assistant"; message: string }>;
  deltaHistory: number[];
  loading: boolean;
  frozen: boolean;
  converged: boolean;
  error?: string | null;
  onSend: (message: string) => void;
  onFreeze: () => void;
}

export function ChatPage({
  schema,
  turns,
  deltaHistory,
  loading,
  frozen,
  converged,
  error,
  onSend,
  onFreeze,
}: ChatPageProps) {
  const [chatWidth, setChatWidth] = useState(420);
  const isDraggingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const newWidth = Math.max(280, Math.min(800, e.clientX - rect.left));
      setChatWidth(newWidth);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  return (
    <div ref={containerRef} className="flex h-full gap-0">
      {/* Left: chat */}
      <div
        style={{ width: `${chatWidth}px` }}
        className="flex flex-shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-800"
      >
        <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Schema refinement chat
          </h2>
        </div>
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            turns={turns}
            loading={loading}
            frozen={frozen}
            converged={converged}
            error={error}
            onSend={onSend}
            onFreeze={onFreeze}
          />
        </div>
      </div>

      {/* Resize handle */}
      <div
        onMouseDown={() => { isDraggingRef.current = true; }}
        className="w-1 cursor-col-resize hover:bg-blue-500 hover:w-1.5 active:bg-blue-600 transition-all"
        title="Drag to resize"
      />

      {/* Right: schema + convergence */}
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        {schema ? (
          <>
            <SchemaPanel key={`schema-v${schema.version}`} schema={schema} />
            <ConvergenceChart deltaHistory={deltaHistory} />
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
      </div>
    </div>
  );
}
