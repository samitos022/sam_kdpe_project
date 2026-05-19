import { useRef, useState, useEffect } from "react";
import { Button } from "../ui/Button";
import type { ChatTurn } from "../../types";
import { ChatMessage } from "./ChatMessage";
import { FreezeButton } from "./FreezeButton";

interface ChatPanelProps {
  turns: ChatTurn[];
  loading: boolean;
  frozen: boolean;
  converged: boolean;
  error?: string | null;
  onSend: (message: string) => void;
  onFreeze: () => void;
}

export function ChatPanel({
  turns,
  loading,
  frozen,
  converged,
  error,
  onSend,
  onFreeze,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
 
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);
 
  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || loading || frozen) return;
    onSend(trimmed);
    setInput("");
  };
 
  return (
    <div className="flex h-full flex-col">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto space-y-3 p-4">
        {turns.map((turn, i) => (
          <ChatMessage key={i} turn={turn} />
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <span className="inline-flex gap-1">
              <span className="animate-bounce">·</span>
              <span className="animate-bounce delay-75">·</span>
              <span className="animate-bounce delay-150">·</span>
            </span>
            Thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>
 
      {/* Error notice */}
      {error && (
        <div className="mx-4 mb-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Convergence notice */}
      {converged && !frozen && (
        <div className="mx-4 mb-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
          Schema has converged. Consider freezing it to start batch extraction.
        </div>
      )}
 
      {/* Input area */}
      {frozen ? (
        <div className="border-t border-zinc-200 p-4 dark:border-zinc-800">
          <p className="text-center text-sm text-zinc-400">
            Schema is frozen — go to Batch Extraction
          </p>
        </div>
      ) : (
        <div className="border-t border-zinc-200 p-4 dark:border-zinc-800">
          <div className="flex gap-2">
            <textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder='e.g. "Merge Boyfriend and Husband into Partner"'
              className="flex-1 resize-none rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-violet-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
            />
            <div className="flex flex-col gap-2">
              <Button onClick={handleSend} loading={loading} size="sm">
                Send
              </Button>
              <FreezeButton onFreeze={onFreeze} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
