import type {
  ChatResponse,
  CreateSessionResponse,
  ExtractionStatus,
  GraphEdge,
  GraphNode,
  GraphStats,
  Schema,
  SchemaUtilization,
  Session,
} from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ─── Sessions ────────────────────────────────────────────────────────────────

export const api = {
  createSession: (domain: string, discoveryFraction = 0.1) =>
    req<CreateSessionResponse>("/sessions/create", {
      method: "POST",
      body: JSON.stringify({ domain, discovery_fraction: discoveryFraction }),
    }),

  getSession: (sessionId: string) =>
    req<Session>(`/sessions/${sessionId}`),

  chat: (sessionId: string, message: string) =>
    req<ChatResponse>(`/sessions/${sessionId}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  freeze: (sessionId: string) =>
    req<{ schema: Schema; message: string }>(`/sessions/${sessionId}/freeze`, {
      method: "POST",
    }),

  getHistory: (sessionId: string) =>
    req<{
      versions: Array<{ version: number; n_classes: number; n_relations: number }>;
      delta_history: number[];
      converged: boolean;
      convergence_turn: number | null;
    }>(`/sessions/${sessionId}/history`),

  // ─── Extraction ────────────────────────────────────────────────────────────

  startExtraction: (sessionId: string) =>
    req<{ message: string; total_documents: number }>(`/sessions/${sessionId}/extract`, {
      method: "POST",
    }),

  getExtractionStatus: (sessionId: string) =>
    req<ExtractionStatus>(`/sessions/${sessionId}/extract/status`),

  // ─── Graph ─────────────────────────────────────────────────────────────────

  getNodes: (sessionId: string, className?: string, limit = 200) => {
    const params = new URLSearchParams({ session_id: sessionId, limit: String(limit) });
    if (className) params.set("class_name", className);
    return req<{ nodes: GraphNode[]; count: number }>(`/graph/nodes?${params}`);
  },

  getEdges: (sessionId: string, predicate?: string, limit = 500) => {
    const params = new URLSearchParams({ session_id: sessionId, limit: String(limit) });
    if (predicate) params.set("predicate", predicate);
    return req<{ edges: GraphEdge[]; count: number }>(`/graph/edges?${params}`);
  },

  searchNodes: (sessionId: string, query: string) =>
    req<{ results: GraphNode[]; count: number }>(
      `/graph/search?${new URLSearchParams({ session_id: sessionId, q: query })}`
    ),

  getGraphStats: (sessionId: string) =>
    req<GraphStats>(`/graph/stats?${new URLSearchParams({ session_id: sessionId })}`),

  getSchemaUtilization: (sessionId: string) =>
    req<SchemaUtilization>(
      `/graph/schema_utilization?${new URLSearchParams({ session_id: sessionId })}`
    ),
};