import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ExtractionStatus } from "../types";

const POLL_INTERVAL_MS = 3000;

const EMPTY_STATUS: ExtractionStatus = {
  status: "not_started",
  processed: 0,
  total: 0,
  errors: [],
  metrics: {
    total_entities: 0,
    total_relations: 0,
    total_unmapped: 0,
    total_repairs: 0,
    schema_drift_count: 0,
  },
  uir: 0,
  sdr: 0,
  progress_pct: 0,
};

export function useExtraction(sessionId: string | null) {
  const [status, setStatus] = useState<ExtractionStatus>(EMPTY_STATUS);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Polling ──────────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (!sessionId || pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.getExtractionStatus(sessionId);
        setStatus(s);
        if (s.status === "done" || s.status === "failed") stopPolling();
      } catch (e) {
        setError((e as Error).message);
        stopPolling();
      }
    }, POLL_INTERVAL_MS);
  }, [sessionId, stopPolling]);

  // Cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  // ── Start ────────────────────────────────────────────────────────────────────

  const startExtraction = useCallback(async (maxDocs?: number) => {
    if (!sessionId) return;
    setError(null);
    try {
      await api.startExtraction(sessionId, maxDocs);
      setStatus((s) => ({ ...s, status: "running" }));
      startPolling();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId, startPolling]);

  return { status, error, startExtraction };
}