import { useState } from "react";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { DOMAIN_LABELS } from "../lib/utils";


// ─── HomePage ─────────────────────────────────────────────────────────────────

interface HomePageProps {
  onSessionCreated: (sessionId: string) => void;
  loading: boolean;
  error: string | null;
  onCreate: (domain: string) => void;
}

export function HomePage({ onSessionCreated: _, loading, error, onCreate }: HomePageProps) {
  const [domain, setDomain] = useState("aita");

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-8">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-zinc-800 dark:text-zinc-100">
          Conversational Graph Extraction
        </h1>
        <p className="mt-2 text-sm text-zinc-500">
          Discover a knowledge graph schema through conversation, then extract at scale.
        </p>
      </div>

      <Card className="w-full max-w-sm space-y-4">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Dataset
          </label>
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
          >
            {Object.entries(DOMAIN_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>

        <div className="rounded-lg bg-zinc-50 p-3 text-xs text-zinc-500 dark:bg-zinc-800/50">
          <p>A 10% sample will be used for schema discovery.</p>
          <p className="mt-1">The remaining 90% is held out for batch extraction.</p>
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 p-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </p>
        )}

        <Button onClick={() => onCreate(domain)} loading={loading} className="w-full">
          {loading ? "Discovering schema…" : "Create session"}
        </Button>
      </Card>
    </div>
  );
}