import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { GraphEdge, GraphNode, SchemaUtilization } from "../types";

export function useGraph(sessionId: string | null) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [utilization, setUtilization] = useState<SchemaUtilization | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadGraph = useCallback(
    async (classFilter?: string) => {
      if (!sessionId) return;
      setLoading(true);
      setError(null);
      try {
        const [nodesRes, edgesRes] = await Promise.all([
          api.getNodes(sessionId, classFilter),
          api.getEdges(sessionId),
        ]);
        setNodes(nodesRes.nodes);
        setEdges(edgesRes.edges);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [sessionId]
  );

  const loadUtilization = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = await api.getSchemaUtilization(sessionId);
      setUtilization(data);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId]);

  const searchNodes = useCallback(
    async (query: string): Promise<GraphNode[]> => {
      if (!sessionId || query.length < 2) return [];
      const res = await api.searchNodes(sessionId, query);
      return res.results;
    },
    [sessionId]
  );

  return { nodes, edges, utilization, loading, error, loadGraph, loadUtilization, searchNodes };
}